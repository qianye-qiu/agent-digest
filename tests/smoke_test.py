#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线冒烟测试：不联网，验证 打分 / 去重 / 可信度 / 配额 / 模板渲染 全链路。
运行： python tests/smoke_test.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import yaml
from digest import (Item, Scorer, dedupe, credibility, quota, render,
                    build_radar, norm_url, CFG_DIR)

CFG = yaml.safe_load((CFG_DIR / "sources.yaml").read_text(encoding="utf-8"))
KW = yaml.safe_load((CFG_DIR / "keywords.yaml").read_text(encoding="utf-8"))
NOW = datetime.now(timezone.utc)


def mk(title, body, cls, tier, stype, url, code="", official="", days=1):
    return Item(title=title, url=url, source_id="test", source_type=stype,
                source_tier=tier, source_class=cls, body=body,
                ts=NOW - timedelta(days=days), code_url=code, official_url=official)


items = [
    mk("LangGraph v0.4.0 release: new persistence layer",
       "This release adds durable execution, checkpointing and a new MCP integration.",
       "official", 1, "github_release", "https://github.com/langchain-ai/langgraph/releases/tag/v0.4.0",
       code="https://github.com/langchain-ai/langgraph",
       official="https://github.com/langchain-ai/langgraph/releases/tag/v0.4.0"),
    mk("MCP spec update: Streamable HTTP replaces SSE",
       "Model Context Protocol revision with streamable http transport.",
       "official", 1, "rss", "https://modelcontextprotocol.io/spec", official="https://modelcontextprotocol.io/spec"),
    mk("Multi-agent memory sharing for long-horizon tasks",
       "We propose a shared memory module for LLM agents, improving planning accuracy.",
       "preprint", 1, "arxiv", "https://arxiv.org/abs/2601.01234", official="https://arxiv.org/abs/2601.01234"),
    mk("Hiring: we are looking for AI agent engineers!",
       "Come join our team, great salary.", "media", 2, "rss", "https://example.com/hiring?utm_source=x"),
    mk("LangGraph v0.4.0 release: new persistence layer",
       "duplicate of the first item, an agent framework release note",
       "media", 2, "rss", "https://example.com/dup?utm_source=y"),
    mk("Prompt injection defense with sandbox tool execution",
       "A guardrail design for agent sandbox and evaluation.",
       "community", 2, "hn", "https://news.ycombinator.com/item?id=1", code="https://github.com/x/y"),
]

sc = Scorer(KW)
kept = []
for it in items:
    it.score = sc.score(it)
    if sc.passes(it):
        it.category = sc.categorize(it)
        kept.append(it)
assert len(kept) == 5, f"噪声应被剔除，实际保留 {len(kept)}"
assert all("hiring" not in (i.title + i.body).lower() for i in kept)

kept = dedupe(kept)
assert len(kept) == 4, f"重复项应被合并，实际 {len(kept)}"
dup = next(i for i in kept if "LangGraph" in i.title)
assert dup.cross_source_count == 2, "多源互证计数应 +1"

for it in kept:
    it.cred, it.cred_reason = credibility(it)
    if it.source_type == "github_release":
        it.tier = "S"
    it.summary, it.why, it.action = it.body[:60], "示例", "示例"

assert all(i.cred >= 2 for i in kept)
rel = next(i for i in kept if "LangGraph" in i.title)
assert rel.cred == 5 and rel.tier == "S", f"官方 Release 应为 A+/S，实际 {rel.cred}/{rel.tier}"
pre = next(i for i in kept if i.source_type == "arxiv")
assert pre.cred == 4, f"预印本应封顶 A(4)，实际 {pre.cred}"
assert "预印本未经同行评议" in pre.cred_reason

picked = quota(kept, KW["thresholds"])
assert len(picked) <= KW["thresholds"]["quota"]["total"]

radar = build_radar(picked, KW)
meta = {"week": "2026-W42", "since": "2026-10-08", "until": "2026-10-15",
        "total": len(picked), "sources_ok": 14, "sources_total": 16,
        "health": {"ok": ["arxiv_agent"], "failed": [{"id": "infoq_cn", "error": "HTTP 404"}],
                   "filtered": {"noise": 1, "dup": 1, "lowcred": 0}},
        "generated_at": "2026-10-15 10:17 UTC+8",
        "disclaimer": "可信度为规则自动标注，重要决策前请人工复核原文"}
md = render(picked, radar, meta)

for must in ["可信度", "★★★★★", "本周技术雷达", "数据健康", "meta.week"]:
    if must == "meta.week":
        assert "meta.week" not in md, "模板变量未渲染"
    else:
        assert must in md, f"周报缺少 {must}"

print(md[:1200])
print("\n--- SMOKE TEST PASSED ---")
print(f"保留 {len(picked)} 条 | 栏目: {sorted({i.category for i in picked})}")
print(f"可信度: {[(i.title[:28], i.cred_label) for i in picked]}")
