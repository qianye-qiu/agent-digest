#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Agent 技术周报自动搜集 —— 可运行骨架
用法:
  python src/digest.py --check-sources          # 校验所有数据源可用性
  python src/digest.py --dry-run                # 全流程跑通但不推送
  python src/digest.py --window 8d --push email # 正式运行并推送
  python src/digest.py --backfill 2026-W40      # 补跑历史周
依赖: pip install requests feedparser PyYAML Jinja2 tenacity
"""
from __future__ import annotations

import argparse, hashlib, json, os, re, smtplib, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.header import Header
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import feedparser
import requests
import yaml
from jinja2 import Environment, FileSystemLoader

# 把 stdout/stderr 强制重配为 utf-8。
# GitHub Actions 的 ubuntu-latest runner 默认 LANG=C，Python 检测到 stdout 非 TTY 时
# 会用 locale.getpreferredencoding() 拿到 ASCII；模板里的 ⚠️/🟢/📄 等 emoji 一 print 就崩，
# 抛 UnicodeEncodeError 让整个脚本 exit 1（2026-10-15 在 Actions 上踩过这个坑）。
# 本机 Windows 默认 GBK 同样会炸，统一兜底最稳。Python 3.7+ 才有的 reconfigure，旧版静默忽略。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
CFG_DIR, TPL_DIR, ARCH_DIR, STATE_DIR = (
    ROOT / "config", ROOT / "templates", ROOT / "archive", ROOT / "state")


def load_dotenv():
    """从 config/.env（优先）或根目录 .env 读取凭据，注入进程环境变量。

    已存在的环境变量优先级更高（不会被文件覆盖），
    这样 GitHub Actions / CI 里用 Secrets 注入时行为不变。
    文件格式: KEY=VALUE，# 开头为注释，值可省略引号。
    """
    for path in (CFG_DIR / ".env", ROOT / ".env"):
        if not path.exists():
            continue
        n = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v
                n += 1
        log(f"  已从 {path.name} 载入 {n} 个环境变量")
        break

# ------------------------------------------------------------------ 数据模型
@dataclass
class Item:
    title: str
    url: str
    source_id: str
    source_type: str
    source_tier: int = 2
    source_class: str = "media"     # official|venue|preprint|community|media|selfmedia
    body: str = ""
    ts: datetime | None = None
    ts_source: str = "declared"     # declared | inferred
    author: str = ""
    repo_url: str = ""
    paper_url: str = ""
    official_url: str = ""
    code_url: str = ""
    dataset_url: str = ""
    extra: dict = field(default_factory=dict)
    score: int = 0
    cred: int = 0
    cred_reason: str = ""
    category: str = "其他值得一看"
    tier: str = "B"
    summary: str = ""
    keywords: list[str] = field(default_factory=list)
    why: str = ""
    action: str = ""
    cross_source_count: int = 1

    @property
    def cred_label(self) -> str:
        return {5: "★★★★★ A+ 官方一手", 4: "★★★★ A 高",
                3: "★★★ B 中", 2: "★★ C 低", 1: "★ D 存疑"}[max(1, min(5, self.cred))]

    @property
    def cred_badge(self) -> str:
        return {5: "🟢", 4: "🟢", 3: "🟡", 2: "🟠", 1: "🔴"}[max(1, min(5, self.cred))]


def _safe_ua(ua: str) -> str:
    """HTTP 头只能走 latin-1，占位符里若含中文会让 requests 直接抛错并使全部源失败。"""
    ua = (ua or "").encode("latin-1", "ignore").decode("latin-1").strip()
    return ua or "AgentDigestBot/1.0"


WAIT_SEC = 1.0
TIMEOUT_SEC = 15          # 由 defaults.timeout_sec 覆盖；10s 会让慢源（deepmind/hf）频繁超时
SESSION = requests.Session()
SESSION.headers["User-Agent"] = _safe_ua(os.getenv("DIGEST_UA", "AgentDigestBot/1.0 (+{{CONTACT_EMAIL}})"))


def get(url, **kw):
    time.sleep(WAIT_SEC)
    r = SESSION.get(url, timeout=TIMEOUT_SEC, **kw)
    r.raise_for_status()
    return r


# ------------------------------------------------------------------ 抓取器
def fetch_arxiv(src, since, until):
    p = dict(src.get("params", {}))
    r = get(src["url"], params=p)
    out = []
    for e in feedparser.parse(r.text).entries:
        out.append(Item(
            title=e.title, url=e.link, source_id=src["id"], source_type="arxiv",
            source_tier=src.get("tier", 2), source_class=src.get("source_class", "preprint"),
            body=e.get("summary", ""), ts=_parse(getattr(e, "published", None)),
            author=", ".join(a.name for a in getattr(e, "authors", [])[:5]),
            paper_url=e.link,
            extra={"arxiv_id": e.id.split("/abs/")[-1],
                   "comment": getattr(e, "arxiv_comment", "")},
        ))
    return out


def fetch_rss(src, since, until):
    r = get(src["url"])
    out = []
    for e in feedparser.parse(r.text).entries:
        ts = _parse(getattr(e, "published", None) or getattr(e, "updated", None))
        out.append(Item(
            title=e.title, url=e.link, source_id=src["id"], source_type="rss",
            source_tier=src.get("tier", 2), source_class=src.get("source_class", "media"),
            body=re.sub(r"<[^>]+>", "", e.get("summary", ""))[:3000], ts=ts,
            author=e.get("author", ""), extra={},
        ))
    return out


def fetch_github_search(src, since, until):
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    q = src["query"].replace("{SINCE}", since.strftime("%Y-%m-%d"))
    r = get(f"https://api.github.com/search/repositories",
            params={"q": q, "sort": src.get("sort", "stars"), "per_page": 50}, headers=headers)
    out = []
    for it in r.json().get("items", []):
        if it.get("stargazers_count", 0) < src.get("min_stars", 0):
            continue
        out.append(Item(
            title=f'{it["full_name"]} — {it.get("description","")[:120]}',
            url=it["html_url"], source_id=src["id"], source_type="github_repo",
            source_tier=src.get("tier", 1), source_class=src.get("source_class", "official"),
            body=it.get("description", "") + " topics:" + ",".join(it.get("topics", [])),
            ts=_parse(it.get("created_at")), repo_url=it["html_url"],
            official_url=it["html_url"], code_url=it["html_url"],
            extra={"stars": it["stargazers_count"], "lang": it.get("language")},
        ))
    return out


def fetch_github_release(src, since, until):
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    out = []
    for repo in src.get("repos", []):
        try:
            r = get(f"https://api.github.com/repos/{repo}/releases",
                    params={"per_page": src.get("per_repo", 5)}, headers=headers)
        except Exception as e:
            log(f"  ! release {repo}: {e}"); continue
        for rel in r.json():
            ts = _parse(rel.get("published_at"))
            if not ts or not (since <= ts <= until):
                continue
            out.append(Item(
                title=f'{repo} {rel.get("tag_name","")} — {rel.get("name","")}',
                url=rel["html_url"], source_id=src["id"], source_type="github_release",
                source_tier=1, source_class="official", body=(rel.get("body") or "")[:3000],
                ts=ts, repo_url=f'https://github.com/{repo}',
                official_url=rel["html_url"], code_url=f'https://github.com/{repo}',
                extra={"repo": repo, "tag": rel.get("tag_name"), "prerelease": rel.get("prerelease")},
            ))
    return out


def fetch_pypi(src, since, until):
    out = []
    for pkg in src.get("packages", []):
        try:
            data = get(f"https://pypi.org/pypi/{pkg}/json").json()
        except Exception as e:
            log(f"  ! pypi {pkg}: {e}"); continue
        for ver, files in (data.get("releases") or {}).items():
            if not files:
                continue
            ts = _parse(files[0].get("upload_time"))
            if not ts or not (since <= ts <= until):
                continue
            out.append(Item(
                title=f"{pkg} {ver} 发布", url=f"https://pypi.org/project/{pkg}/{ver}/",
                source_id=src["id"], source_type="pypi", source_tier=1,
                source_class="official", body=f"{pkg} 发布新版本 {ver}", ts=ts,
                official_url=f"https://pypi.org/project/{pkg}/{ver}/",
                extra={"package": pkg, "version": ver},
            ))
    return out


def fetch_hn(src, since, until):
    p = dict(src.get("params", {}))
    p["numericFilters"] = f"created_at_i>{int(since.timestamp())}"
    r = get(src["url"], params=p)
    out = []
    for h in r.json().get("hits", []):
        if (h.get("points") or 0) < src.get("min_points", 0):
            continue
        url = h.get("url") or f'https://news.ycombinator.com/item?id={h["objectID"]}'
        out.append(Item(
            title=h.get("title", ""), url=url, source_id=src["id"], source_type="hn",
            source_tier=src.get("tier", 2), source_class=src.get("source_class", "community"),
            body=h.get("story_text") or "", ts=_parse(h.get("created_at")),
            author=h.get("author"), code_url=url if "github.com" in url else "",
            extra={"points": h.get("points"), "comments": h.get("num_comments"),
                   "discuss": f'https://news.ycombinator.com/item?id={h["objectID"]}'},
        ))
    return out


def fetch_json_generic(src, since, until):
    """按 jq_like 映射的通用 JSON 源（如 HF Daily Papers）"""
    m = src["jq_like"]
    data = get(src["url"]).json()
    out = []
    for row in data:
        title, body = _dig(row, m["title"]), _dig(row, m["body"]) or ""
        out.append(Item(
            title=title, url=m["url"].format(**row), source_id=src["id"],
            source_type="json", source_tier=src.get("tier", 2),
            source_class=src.get("source_class", "media"), body=body,
            ts=_parse(_dig(row, m["ts"])), paper_url=m["url"].format(**row),
            extra={k: _dig(row, v) for k, v in (m.get("extra") or {}).items()},
        ))
    return out


def _openalex_abstract(inv):
    """OpenAlex 的摘要是倒排索引 {word: [pos,...]}，还原成纯文本。"""
    if not isinstance(inv, dict):
        return ""
    slots = []
    for w, poss in inv.items():
        for i in poss or []:
            while len(slots) <= i:
                slots.append("")
            slots[i] = w
    return " ".join(s for s in slots if s)


def fetch_openalex(src, since, until):
    """论文源兜底：arXiv 出口被限流时的替代（OpenAlex 收录 arXiv 预印本与期刊论文）。"""
    p = dict(src.get("params", {}))
    if "filter" in p:
        p["filter"] = (p["filter"]
                       .replace("{SINCE}", f"{since:%Y-%m-%d}")
                       .replace("{UNTIL}", f"{until:%Y-%m-%d}"))
    r = get(src["url"], params=p)
    out = []
    for w in r.json().get("results", []):
        loc = w.get("primary_location") or {}
        url = (w.get("doi") or loc.get("landing_page_url")
               or loc.get("pdf_url") or "https://openalex.org/")
        if url and not url.startswith("http"):
            url = "https://doi.org/" + url.lstrip("/")
        src_name = ((loc.get("source") or {}).get("display_name") or "")
        # 预印本（arXiv 等仓库）按预印本评级，正式发表按 venue 评级
        is_preprint = (w.get("type") in ("preprint", "posted-content")
                       or "arXiv" in src_name)
        out.append(Item(
            title=w.get("title") or w.get("display_name") or "", url=url,
            source_id=src["id"], source_type="openalex",
            source_tier=src.get("tier", 1),
            source_class="preprint" if is_preprint else src.get("source_class", "venue"),
            body=_openalex_abstract(w.get("abstract_inverted_index"))[:3000],
            ts=_parse(w.get("publication_date")), paper_url=url,
            extra={"venue": src_name, "cited_by": w.get("cited_by_count", 0)},
        ))
    return out


FETCHERS = {
    "arxiv": fetch_arxiv, "rss": fetch_rss, "github_search_repo": fetch_github_search,
    "github_release": fetch_github_release, "pypi": fetch_pypi,
    "hn": fetch_hn, "json": fetch_json_generic, "openalex": fetch_openalex,
}


# ------------------------------------------------------------------ 工具函数
def _parse(v):
    """统一转为带时区的 UTC datetime。PyPI 等源给的是无时区的 naive 时间，
    不补齐就会在和 UTC 窗口比较时抛 TypeError。"""
    if not v:
        return None
    from email.utils import parsedate_to_datetime
    dt = None
    try:
        if isinstance(v, (int, float)):
            dt = datetime.fromtimestamp(v, timezone.utc)
        elif isinstance(v, str) and v.endswith("Z"):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        elif isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}T", v):
            dt = datetime.fromisoformat(v)
        else:
            dt = parsedate_to_datetime(v)
    except Exception:
        try:
            dt = datetime.fromisoformat(v)
        except Exception:
            return None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _dig(obj, path):
    cur = obj
    for k in path.split("."):
        cur = (cur or {}).get(k) if isinstance(cur, dict) else None
    return cur


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def norm_url(u: str) -> str:
    p = urlparse(u or "")
    q = {k: v for k, v in parse_qsl(p.query) if not k.startswith("utm_") and k != "ref"}
    return urlunparse(("", "", p.netloc.lower(), p.path.rstrip("/"), urlencode(q), ""))


def shingles(t: str) -> set[str]:
    t = re.sub(r"[^\w\s]", " ", (t or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    return {t[i:i + 12] for i in range(max(1, len(t) - 11))}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0


# ------------------------------------------------------------------ 打分 / 去重 / 可信度
class Scorer:
    def __init__(self, kw):
        self.w = kw["weights"]; self.t = kw["thresholds"]
        self.core, self.frame, self.topic, self.neg = (
            kw["core"], kw["frame"], kw["topic"], kw["neg"])
        self.categories = kw["categories"]

    def _hits(self, text, words):
        tl = (text or "").lower()
        return sum(1 for w in words if w.lower() in tl)

    def score(self, it: Item) -> int:
        tl, bl = (it.title or "").lower(), (it.body or "").lower()
        s = self.w["core_in_title"] * self._hits(tl, self.core)
        s += self.w["core_in_body"] * self._hits(bl, self.core)
        s += self.w["frame_any"] * self._hits(tl + " " + bl, self.frame)
        s += self.w["topic_any"] * self._hits(tl + " " + bl, self.topic)
        s += self.w["neg_any"] * self._hits(tl + " " + bl, self.neg)
        if it.code_url or it.repo_url:
            s += self.w["has_code_bonus"]
        if it.source_tier == 1:
            s += self.w["tier1_bonus"]
        return s

    def passes(self, it: Item) -> bool:
        if self._hits(it.title + " " + it.body, self.neg):
            return False
        if self.t["require_core_hit"] and not self._hits(it.title + " " + it.body, self.core):
            return False
        return it.score >= self.t["min_score"]

    def categorize(self, it: Item) -> str:
        text = (it.title + " " + it.body).lower()
        best, bn = "工程实践与案例", 0
        for cat, words in self.categories.items():
            n = self._hits(text, words)
            if n > bn:
                best, bn = cat, n
        if it.source_type in ("arxiv", "json") and "论文与算法" in self.categories:
            if "评测" not in best:
                return "论文与算法"
        return best


def dedupe(items: list[Item]) -> list[Item]:
    """L1 URL 归一 -> L2 标题相似 -> L3 实体合并(arXiv ID / repo@version) -> 互证计数"""
    by_url, out = {}, []
    for it in items:
        k = norm_url(it.url)
        if k in by_url:
            old = by_url[k]
            old.cross_source_count += 1
            if it.cred > old.cred or it.source_tier < old.source_tier:
                old.url = it.url if it.source_tier < old.source_tier else old.url
            continue
        by_url[k] = it
        sh = shingles(it.title)
        dup = next((o for o in out if jaccard(sh, shingles(o.title)) >= 0.85), None)
        if dup:
            dup.cross_source_count += 1
            continue
        out.append(it)
    return out


def credibility(it: Item) -> tuple[int, str]:
    base = {"official": 5, "venue": 5, "preprint": 4,
            "community": 3, "media": 2, "selfmedia": 1}.get(it.source_class, 2)
    ev = 0
    ev += 1 if (it.official_url or it.paper_url) else 0
    ev += 1 if (it.repo_url or it.dataset_url or it.code_url) else 0
    ev -= 1 if it.source_class in ("media", "selfmedia") else 0
    cons = 1 if it.cross_source_count >= 2 else (0 if it.cross_source_count == 1 else -1)
    if it.ts_source == "inferred":
        cons = min(cons, 0)
    score = max(1, min(5, base + ev + cons))
    reason = f"来源={it.source_class}({base}) 证据链{ev:+d} 互证{cons:+d}"
    if it.source_class == "preprint":
        # 预印本未经过同行评议，可信度上限压到 A(4)；
        # 仅在"多源互证 + 有可复现代码"时才允许升到 5
        cap = 5 if (it.cross_source_count >= 2 and (it.repo_url or it.code_url)) else 4
        if score > cap:
            reason += f"；预印本封顶至{cap}"
        score = min(score, cap)
        reason += "；预印本未经同行评议"
    if it.ts_source == "inferred":
        reason += "；时间戳缺失按抓取时刻推定"
    return score, reason


def quota(items: list[Item], t: dict) -> list[Item]:
    S = [i for i in items if i.tier == "S"]
    A = sorted([i for i in items if i.tier != "S" and i.score >= t["tier_a_score"]],
               key=lambda x: -x.score)[:t["quota"]["A"]]
    B = sorted([i for i in items if i.tier != "S" and i.score < t["tier_a_score"]],
               key=lambda x: -x.score)[:t["quota"]["B"]]
    out = S + A + B
    return sorted(out, key=lambda x: (0 if x.tier == "S" else 1, -x.score))[:t["quota"]["total"]]


# ------------------------------------------------------------------ 摘要
def summarize(it: Item, llm=None) -> Item:
    """LLM 优先；不可用则抽取式降级。严禁编造链接/版本号/数字。"""
    if llm:
        try:
            r = llm(it.title, it.body[:3000])
            it.summary, it.why, it.action = r["summary"][:120], r["why"][:60], r["action"][:60]
            it.keywords = r.get("keywords", [])[:5]
            return it
        except Exception as e:
            log(f"  ! llm fallback: {e}")
    first = re.split(r"(?<=[。.!?])\s", (it.body or "").strip())
    it.summary = (first[0][:120] if first and first[0] else it.title) + "（自动摘要，未润色）"
    it.why = "—"; it.action = "—"
    return it


def llm_client():
    key = os.getenv("LLM_API_KEY")
    if not key:
        return None
    base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")

    def call(title, body):
        prompt = ("你是面向工程师的技术编辑。只使用给定原文中的信息，禁止编造链接、版本号、数字。\n"
                  f"标题：{title}\n原文：{body}\n"
                  "输出 JSON: {summary(≤80字), keywords[string x3], why(≤40字), action(≤40字)}")
        r = SESSION.post(f"{base}/chat/completions",
                         headers={"Authorization": f"Bearer {key}"},
                         json={"model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                               "temperature": 0.2,
                               "messages": [{"role": "user", "content": prompt}]}, timeout=60)
        r.raise_for_status()
        return json.loads(re.sub(r"^```json|```$", "",
                                 r.json()["choices"][0]["message"]["content"]).strip())
    return call


# ------------------------------------------------------------------ 渲染 / 推送 / 归档
def render(items, radar, meta, tmpl="report.md.j2") -> str:
    env = Environment(loader=FileSystemLoader(str(TPL_DIR)), keep_trailing_newline=True)
    return env.get_template(tmpl).render(items=items, radar=radar, meta=meta)


def deliver(md: str, push_cfg, channels, meta):
    if "email" in channels:
        e = push_cfg["email"]
        # 占位符 {{XXX}} 用同名环境变量兜底（便于在 GitHub Actions / CI 中通过 Secrets 注入，
        # 同时也支持 .env 文件方式；只要环境变量存在就优先用，不存在则按配置原样）
        for k in ("host", "user", "password", "to"):
            v = e.get(k, "")
            if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
                env_key = v[2:-2]
                e[k] = os.getenv(env_key, "") or v
        # 关键凭据缺失则优雅跳过（周报已写盘归档）
        missing = [k for k in ("host", "user", "password", "to") if not e.get(k) or e[k].startswith("{{")]
        if missing:
            log(f"  ! 邮件未发送：SMTP 凭据不完整（缺 {', '.join(missing)}），可在 Secrets 配 SMTP_HOST/SMTP_USER/SMTP_PASS/MAIL_TO 后重试")
        else:
            msg = MIMEText(md, "plain", "utf-8")
            msg["Subject"] = Header(f'{e.get("subject_prefix", "[Agent周报]")} {meta["week"]}', "utf-8")
            msg["From"], msg["To"] = e["user"], e["to"]
            port = int(e.get("port") or 587)
            with smtplib.SMTP(e["host"], port, timeout=30) as s:
                s.starttls(); s.login(e["user"], e["password"])
                s.sendmail(e["user"], e["to"].split(","), msg.as_string())
            log("  > 邮件已发送")
    if "im" in channels or "dingtalk" in channels or "slack" in channels:
        hook = push_cfg.get("im_webhook", "")
        if isinstance(hook, str) and hook.startswith("{{") and hook.endswith("}}"):
            hook = os.getenv(hook[2:-2], "") or ""
        if hook and not hook.startswith("{{"):
            SESSION.post(hook, json={"msgtype": "markdown",
                                     "markdown": {"title": f'Agent周报 {meta["week"]}',
                                                  "text": md[:1500] + "\n\n[全文见归档]"}}, timeout=15)
            log("  > IM 已推送")
    if "github_issue" in channels:
        log("  > Issue 由 Actions 步骤创建（见 weekly-digest.yml）")


def archive(md, items, raw, week):
    d = ARCH_DIR / week[:4]; d.mkdir(parents=True, exist_ok=True)
    (d / f"{week}.md").write_text(md, encoding="utf-8")
    (d / f"{week}.json").write_text(
        json.dumps([asdict(i) for i in items], ensure_ascii=False, default=str, indent=2),
        encoding="utf-8")
    (d / f"{week}.raw.json").write_text(
        json.dumps([asdict(i) for i in raw], ensure_ascii=False, default=str), encoding="utf-8")
    (ROOT / "archive" / "latest.md").write_text(md, encoding="utf-8")


def load_seen():
    p = STATE_DIR / "seen.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def update_seen(items, keep_days=14):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    seen = load_seen(); now = time.time()
    seen = {k: v for k, v in seen.items() if now - v < keep_days * 86400}
    for it in items:
        seen[hashlib.md5(norm_url(it.url).encode()).hexdigest()] = now
        seen["t:" + hashlib.md5(it.title.lower().encode()).hexdigest()] = now
    (STATE_DIR / "seen.json").write_text(json.dumps(seen), encoding="utf-8")


def seen_before(it, seen):
    return (hashlib.md5(norm_url(it.url).encode()).hexdigest() in seen
            or "t:" + hashlib.md5(it.title.lower().encode()).hexdigest() in seen)


def build_radar(items, kw) -> list[dict]:
    """本期 TOPIC 词频生成动态条目 + 固定兜底"""
    text = " ".join((i.title + " " + i.body) for i in items).lower()
    freq = {w: text.count(w) for w in kw["topic"]}
    hot = [w for w, c in sorted(freq.items(), key=lambda x: -x[1])[:3] if c >= 3]
    radar = list(kw["learning_radar_fixed"])
    for i, w in enumerate(hot):
        radar.append({"priority": f"P{1 + i}", "topic": f"本期热词：{w}",
                      "why": f"本期出现 {freq[w]} 次，是当前社区焦点",
                      "how": f"找 1 篇涉及 {w} 的原文精读，并在本地项目做一次最小验证",
                      "output": "200 字笔记 + 可运行片段"})
    return radar


# ------------------------------------------------------------------ 主流程
def run(window_days=8, do_push=True, channels=None, week=None):
    cfg = yaml.safe_load((CFG_DIR / "sources.yaml").read_text(encoding="utf-8"))
    kw = yaml.safe_load((CFG_DIR / "keywords.yaml").read_text(encoding="utf-8"))
    SESSION.headers["User-Agent"] = _safe_ua(cfg["defaults"].get("user_agent"))
    # timeout_sec 由配置驱动（此前硬编码 10s，改配置不生效）
    global TIMEOUT_SEC
    TIMEOUT_SEC = int(cfg["defaults"].get("timeout_sec", TIMEOUT_SEC))
    now = datetime.now(timezone.utc)
    since, until = now - timedelta(days=window_days), now
    week = week or now.strftime("%G-W%V")
    log(f"[1/8] 抓取窗口 {since:%F} ~ {until:%F} (UTC)")

    raw, health = [], {"ok": [], "failed": [], "filtered": {"noise": 0, "dup": 0, "lowcred": 0}}
    srcs = [s for s in cfg["sources"] if s["type"] in FETCHERS]

    def collect(batch, parallel=True):
        got_all = []
        if parallel:
            with ThreadPoolExecutor(max_workers=cfg["defaults"]["concurrency"]) as ex:
                futs = {ex.submit(FETCHERS[s["type"]], s, since, until): s for s in batch}
                for f in as_completed(futs):
                    s = futs[f]
                    try:
                        got = f.result(); got_all += got; health["ok"].append(s["id"])
                        log(f"  ✓ {s['id']:<24} {len(got)} 条")
                    except Exception as e:
                        health["failed"].append({"id": s["id"], "error": str(e)[:120]})
                        log(f"  ✗ {s['id']:<24} {e}")
        else:
            # arXiv 官方要求「一次一个请求、间隔 ≥3s」，并发必然 429 → 串行
            for s in batch:
                time.sleep(3)
                try:
                    got = FETCHERS[s["type"]](s, since, until)
                    got_all += got; health["ok"].append(s["id"])
                    log(f"  ✓ {s['id']:<24} {len(got)} 条")
                except Exception as e:
                    health["failed"].append({"id": s["id"], "error": str(e)[:120]})
                    log(f"  ✗ {s['id']:<24} {e}")
        return got_all

    # 先串行跑 arXiv（限流最严），再并发跑其余源
    raw += collect([s for s in srcs if s["type"] == "arxiv"], parallel=False)
    raw += collect([s for s in srcs if s["type"] != "arxiv"], parallel=True)

    for it in raw:                                     # 时间戳兜底
        if it.ts is None:
            it.ts, it.ts_source = now, "inferred"
    raw = [i for i in raw if since <= i.ts <= until + timedelta(hours=24)]
    log(f"[2/8] 时间过滤后 {len(raw)} 条")

    sc = Scorer(kw)
    seen = load_seen()
    kept = []
    for it in raw:
        it.score = sc.score(it)
        if not sc.passes(it):
            health["filtered"]["noise"] += 1; continue
        if seen_before(it, seen):
            health["filtered"]["dup"] += 1; continue
        it.category = sc.categorize(it)
        kept.append(it)
    log(f"[3/8] 相关性过滤后 {len(kept)} 条")

    kept = dedupe(kept)                                # [4/8]
    log(f"[4/8] 去重后 {len(kept)} 条")

    for it in kept:                                    # [5/8]
        it.cred, it.cred_reason = credibility(it)
        if it.cred <= 1:
            health["filtered"]["lowcred"] += 1
    kept = [i for i in kept if i.cred >= 2]
    for it in kept:                                    # S 层：Tier-1 官方 Release / 协议变更
        if it.source_type in ("github_release", "pypi") and it.source_tier == 1:
            it.tier = "S"
    log(f"[5/8] 可信度标注完成 ({len(kept)} 条)")

    picked = quota(kept, kw["thresholds"])             # [6/8]
    llm = llm_client()
    picked = [summarize(i, llm) for i in picked]
    log(f"[6/8] 定稿 {len(picked)} 条")

    radar = build_radar(picked, kw)                    # [7/8]
    meta = {"week": week, "since": f"{since:%Y-%m-%d}", "until": f"{until:%Y-%m-%d}",
            "total": len(picked), "sources_ok": len(health["ok"]),
            "sources_total": len(cfg["sources"]), "health": health,
            "generated_at": datetime.now(timezone(timedelta(hours=8))).strftime("%F %H:%M UTC+8"),
            "disclaimer": "可信度为规则自动标注，重要决策前请人工复核原文"}
    md = render(picked, radar, meta)

    archive(md, picked, raw, week)                     # [8/8]
    if do_push:
        deliver(md, cfg["push"], channels or cfg["push"]["channels"], meta)
        update_seen(picked)
    else:
        log("  (dry-run) 跳过推送与 seen 更新")
    print(md)
    return md


def check_sources():
    cfg = yaml.safe_load((CFG_DIR / "sources.yaml").read_text(encoding="utf-8"))
    ok = bad = 0
    for s in cfg["sources"]:
        try:
            r = SESSION.get(s["url"], timeout=TIMEOUT_SEC)
            status = "OK " if r.status_code == 200 else f"HTTP {r.status_code}"
            if r.status_code == 200: ok += 1
            else: bad += 1
        except Exception as e:
            status, bad = f"ERR {str(e)[:40]}", bad + 1
        flag = " [optional]" if s.get("optional") else ""
        print(f"{status:<16} {s['id']:<26} {s['type']:<18}{flag}")
    print(f"\n可用 {ok} / 失效 {bad} —— 失效源请更新 config/sources.yaml")

    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        print(f"GITHUB_TOKEN: 已配置（{len(tok)} 字符）→ GitHub API 限流 5000 次/小时")
    else:
        print("GITHUB_TOKEN: 未配置 → GitHub API 限流仅 60 次/小时，"
              "Release/搜索类源大概率采集中断（把 token 写进 config/.env 即可）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="8d")
    ap.add_argument("--push", default="", help="逗号分隔: email,im,github_issue")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check-sources", action="store_true")
    ap.add_argument("--backfill", default="", help="如 2026-W40")
    a = ap.parse_args()
    load_dotenv()

    if a.check_sources:
        check_sources(); sys.exit(0)
    chans = [c.strip() for c in a.push.split(",") if c.strip()] or None
    run(window_days=int(a.window.rstrip("d")), do_push=not a.dry_run,
        channels=chans, week=a.backfill or None)
