# agent-digest｜AI Agent 技术周报自动搜集

每周自动搜集近 7 天 AI Agent（智能体）领域的技术资讯，产出面向开发人员的中文技术周报。
完整设计见：[`方案设计-AI-Agent技术周报自动搜集.md`](../方案设计-AI-Agent技术周报自动搜集.md)

## ✅ 已在 WorkBuddy 内启用定时任务（免 GitHub 仓库）

- **任务名**：AI Agent 技术周报（每周一 10:17）
- **频率**：每周一 10:17（北京时间）自动触发，下次运行 2026-10-19 10:17
- **工作方式**：以联网搜索为主采集四类来源；本机 `api.github.com` / `pypi.org` 可达，
  `export.arxiv.org` / `huggingface.co` / `hn.algolia.com` 被网络策略拦截时自动用搜索补齐
- **产出**：写入 `archive/YYYY/YYYY-Wnn.md`
- **投递**：智能体邮箱 → `1822964623@qq.com`（Markdown 正文，`skip_confirmation=true` 以免无人值守时卡在确认步骤）+ 会话内 present_files
- ✅ **邮件通道已验证**（2026-10-15）：测试邮件发送成功并出现在已发送列表。
  - 发件地址 `rfuc0815@agent.qq.com`（建议加白名单，免得进垃圾箱）
  - 发信配额 50 封/天，周报 1 封/周，无压力
  - 若后续出现 `not_bound`（邮箱未开通），任务不会中断，周报照常归档 + 会话内呈现，仅跳过邮件
- 采集策略与网络实测见下节「本机网络实测」

## 快速开始

```bash
pip install -r requirements.txt

# 1) 先校验数据源（RSS 地址变动频繁，务必先跑）
python src/digest.py --check-sources

# 2) 本地试跑（不推送，直接打印周报）
python src/digest.py --dry-run

# 3) 正式运行并推送
python src/digest.py --window 8d --push email,github_issue
```

## 填写占位符

所有凭据统一写在 **`config/.env`**（复制 `config/.env.example` 改名为 `.env` 即可，已在 `.gitignore` 中，不会被提交）。
程序启动自动加载；**已存在的同名环境变量优先级更高**，所以在 CI 里用 Secrets 注入时行为不变。

| 占位符 | 位置 | 是否必填 |
|---|---|---|
| `{{推送渠道}}` | `config/sources.yaml` → `push.channels`（`email` / `im` / `github_issue`） | 看部署方式 |
| `{{SMTP_HOST}}` `{{SMTP_USER}}` `{{SMTP_PASS}}` `{{MAIL_TO}}` | `config/.env` 或 Actions Secrets | 仅邮件投递需要 |
| `{{IM_WEBHOOK}}` | 钉钉 / 飞书 / Slack Incoming Webhook | 仅 IM 推送需要 |
| `{{GITHUB_TOKEN}}` | `config/.env`（本机跑）；**GitHub Actions 下免填**，用 Actions 自动注入的 token | 本机必填 |
| `{{LLM服务}}` | `config/.env` 的 `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`，不填自动降级为抽取式摘要 | 否 |
| `{{联系邮箱}}` | `config/sources.yaml` 的 `user_agent` | 否 |

> **最省事的部署**是推到 GitHub Actions——`config/.env` 一个文件都不用建，邮件也不配也能跑（只是少了邮件投递）。详见下文「部署到 GitHub Actions」一节。

## 获取 GITHUB_TOKEN（3 分钟）

不配 Token 时 GitHub API 只有 **60 次/小时**的限额（且是共享 IP 额度，很容易被别人打满）；
配了之后是 **5000 次/小时**。本方案只需要「读取公开仓库」权限，**可以不勾选任何 scope**。

### 方案 A：Fine-grained token（推荐）

1. 登录 GitHub → 右上角头像 → **Settings**
2. 左侧最底部 **Developer settings** → **Personal access tokens** → **Fine-grained tokens**
3. 点 **Generate new token**
4. 填写：
   - **Token name**：`agent-digest`
   - **Expiration**：`90 days`（最长 1 年，到期前记得轮换）
   - **Resource owner**：选自己的账号
   - **Repository access**：选 **Public Repositories (read-only)** ← 关键
   - **Permissions**：不用勾选任何写权限，保持默认即可
5. 点 **Generate token**
6. **立刻复制** `github_pat_` 开头的字符串（只显示这一次，关掉页面就没了）

### 方案 B：Classic token（步骤更少）

1. Settings → Developer settings → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**
2. Note 填 `agent-digest`，Expiration 选 90 days
3. **所有 scope 都不勾选**（不勾任何 scope 的 classic token 依然能把限流提到 5000/h，且只能读公开数据，安全性最高）
4. Generate → 复制 `ghp_` 开头的字符串

### 填到哪里

```bash
# 复制模板后编辑
cp config/.env.example config/.env
# 填入：GITHUB_TOKEN=github_pat_xxxx...（或 ghp_xxxx...）
```

验证是否生效：

```bash
python src/digest.py --check-sources
# 末尾会打印：
#   GITHUB_TOKEN: 已配置（40 字符）→ GitHub API 限流 5000 次/小时
# 或
#   GITHUB_TOKEN: 未配置 → ... 限流仅 60 次/小时
```

### GitHub Actions 场景（不用 .env）

仓库页面 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，
名字填 `GH_TOKEN`，值粘贴 token。workflow 里已经写好了 `GITHUB_TOKEN: ${{ secrets.GH_TOKEN }}`，无需改代码。

### 安全注意

- 不要把 token 写进 `sources.yaml` 或直接提交到仓库；`.env` 已在 `.gitignore` 里
- 泄露了就立刻去 token 列表点 **Delete / Revoke**，不要只是删文件
- 到期前轮换一次即可，周报一周只跑一次，用量极低

## 目录

```
config/sources.yaml    数据源清单（增源不改代码）
config/keywords.yaml   关键词权重、收录阈值、配额、学习雷达兜底
src/digest.py          主流程 + 各 fetcher（可运行骨架）
templates/report.md.j2 周报模板（可信度为强制字段）
.github/workflows/     每周一 UTC 02:17 定时触发
state/seen.json        14 天去重缓存
archive/YYYY/YYYY-Wnn.md|.json|.raw.json   归档（原始快照保留 180 天）
```

## 流水线

抓取（多源并发，单源失败隔离）→ 时间窗过滤（7d+1d 重叠）→ 相关性打分（CORE 必须命中，score≥6）
→ 三级去重（URL/标题/实体）→ 可信度标注（A+~D，D 级剔除）→ 分层配额（S/A/B，共 15–25 条）
→ LLM 摘要（失败降级抽取式）→ 渲染 → 推送 → 归档

## 可信度规则（摘要）

```
base:        官方一手 5 / 顶会 5 / 预印本 4 / 社区 3 / 媒体 2 / 自媒体 1
evidence:    官方或论文直链 +1；可复现仓库 +1；二手转述 -1
consistency: ≥2 源互证 +1；时间戳缺失 -1
cred = clamp(base + evidence + consistency, 1, 5)  →  5:A+ / 4:A / 3:B / 2:C / 1:D(不收录)
特殊封顶：预印本 ≤ 4（除非多源互证且有可复现代码）
```

## 测试

```bash
python tests/smoke_test.py     # 离线冒烟：打分/去重/可信度/配额/渲染全链路，不联网
```

## 本机网络实测（2026-10-15）

| 端点 | 结果 | 说明 |
|---|---|---|
| `api.github.com` | ✅ 200 | 配 Token 后 5000 次/小时；未配 60 次/小时且易被共享 IP 打满 |
| `pypi.org` | ✅ 200 | 稳定 |
| `openai.com/blog/rss.xml` | ✅ 200（偶发 502） | 一次约 1300 条，靠时间窗过滤 |
| `infoq.cn/feed` | ✅ 200 | 稳定 |
| `api.openalex.org` | ✅ 200 | 2026-10-15 新增为论文源兜底（同样收录 arXiv 预印本），实测 8 天内 621 条 |
| `simonwillison.net/atom/everything/` | ✅ 200 | 2026-10-15 新增，用于补社区视角 |
| `export.arxiv.org` | ⚠️ 可达但限流 | 走 https；http 直接 403。串行 + 间隔 3s 仍返回 `429 Rate exceeded`，约 4 分钟内连续 7 次请求全部被拒 —— 出口 IP 被共享代理拉黑，脚本侧无法绕过 |
| `huggingface.co` | ❌ 超时 / 502 | 被网络策略拦截 |
| `hn.algolia.com` | ❌ 超时 | 被网络策略拦截 |
| `reddit.com` | ❌ 超时 / 502 | 被网络策略拦截 |
| `deepmind.google` | ⚠️ 偶发 | SSL EOF / 超时，成功率约 50% |
| `anthropic.com` RSS | ❌ 404 | 官方已不提供 RSS（rss.xml / news/rss.xml / feed.xml 全 404） |
| `llamaindex.ai` RSS | ❌ 404 | 官方地址失效 |
| `blog.langchain.dev/rss/` | ⚠️ 返回 HTML | 解析出 0 条，静默失败；LangChain 动态改由 GitHub Release 覆盖 |

结论：**本机无法稳定拿到「论文」和「社区」两大类源**，所以定时 automation 走
「联网搜索为主 + 脚本补 GitHub/PyPI/官方博客」的混合策略。换到无此限制的环境（或 CI
runner）后，`src/digest.py` 可直接独立运行，两条路线互为备份。

## 调优建议

- 前 2 周人工复核，按"有效率"调 `config/keywords.yaml` 的 `min_score` 与 `quota`
- 信息茧房：`sources.yaml` 中保留 `explore: true` 的探索类源
- 回溯重放：`--backfill 2026-W40` 可用新规则重算历史周

## 部署到 GitHub Actions（真正设备无关）

如果想让周报**与本机完全解耦**——关机、换电脑、换城市都不影响——把 `agent-digest/` 整个目录推到 GitHub，Actions 会按 `cron` 自动每周跑。

**为什么选这个**：与 WorkBuddy 内的「本地定时任务」不同，GitHub Actions 跑在 GitHub 自己的 Ubuntu runner 上，**不依赖你的电脑、客户端、venv、本地路径**。每周的周报还会作为 git commit 留在仓库里，**既是历史档案，也防止 GitHub 因仓库 60 天无活动停用 scheduled workflow**。

### 一、准备仓库

1. 打开 GitHub → **New repository** → 名字建议 `agent-digest` → **Create（不勾选任何初始化选项）**
2. 本机 push：

   ```bash
   cd agent-digest
   git init
   git add .
   git commit -m "init: agent-digest"
   git branch -M main
   git remote add origin git@github.com:<你的用户名>/agent-digest.git   # 或 https://...
   git push -u origin main
   ```

3. 推上去后，仓库根目录里应该能看到 `.github/workflows/weekly-digest.yml`、`src/`、`config/`、`tests/`、`requirements.txt`、`README.md`

### 二、（可选）配 Secrets

仓库 **Settings → Secrets and variables → Actions → New repository secret**。**不配任何 Secret 也能跑**，只是少了「邮件」投递；其它能力（GitHub API 5000/h 认证额度、自动 commit、自动创建 Issue）全部由 Actions 自动注入的 `GITHUB_TOKEN` 承担，**不需要你自己建 PAT**。

| Secret | 必填？ | 用途 |
|---|---|---|
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASS` `MAIL_TO` | 否 | 邮件投递。QQ 邮箱需开启 SMTP 并用「授权码」作为 `SMTP_PASS`；Gmail/163/自建同理 |
| `IM_WEBHOOK` | 否 | 钉钉 / 飞书 / Slack Incoming Webhook，用于失败告警 |
| `LLM_API_KEY` `LLM_BASE_URL` `LLM_MODEL` | 否 | 启用 LLM 摘要（不填则自动降级为抽取式摘录） |

### 三、首次试跑

1. 仓库 → **Actions** 标签 → 左侧选 `weekly-agent-digest`
2. 右侧 **Run workflow** → **Run workflow**（默认参数即可）
3. 等 1–3 分钟，看每个步骤是否绿：
   - `Check sources health` 标 ✗ 也算正常——这是网络可达性探测，单源失败隔离
   - `Run digest` 必须 ✓；失败的话看日志的「🩺 数据健康」段
   - `Commit archive back to repo` / `Open / update weekly Issue` 也必须 ✓
4. 跑完后：
   - 仓库多了 `archive/2026/2026-Wnn.md` 文件（这就是周报正文）
   - 仓库多了 `archive/latest.md`（同一份的副本，方便快速访问）
   - 仓库多了一条带 `digest` 标签的 Issue，标题是「Agent 技术周报 2026-Wnn」

### 四、之后的运维

| 想做的事 | 怎么做 |
|---|---|
| 改关键词权重 / 源清单 | 本地改 `config/keywords.yaml` 或 `config/sources.yaml`，`git commit && git push` 即可。下次跑自动生效 |
| 补跑历史周 | Actions 页面 Run workflow → `week` 填 `2026-W40` 之类的 ISO 周编号 |
| 改时间窗 | Run workflow → `window` 填天数；想换成"近 3 天"可写 4 |
| 暂停 | 编辑 `.github/workflows/weekly-digest.yml`，把 `schedule:` 段注释掉后 push；或仓库 Settings → Actions → 禁用 workflow |
| 删除 | 直接删 `.github/workflows/weekly-digest.yml` 或删仓库 |
| 查失败原因 | 仓库 Actions → 失败的 run → 看日志；可选配置 `IM_WEBHOOK` 让失败主动推送到群 |

### 五、给 cron 校准的实操心法

- GitHub Actions 调度是 **UTC**，`17 2 * * 1` = 北京时间周一 10:17；±5 分钟延迟属正常
- 如果连续几周没收到周报，先去 Actions 标签看是否有失败 run
- 仓库 60 天无任何活动，GitHub 会静默停用 scheduled workflow。周报 commit 本身是活动，所以只要周报正常出就不会触发；保险起见可每月手动 Run workflow 一次
- 想换时区，cron 改算成 UTC 即可（不同时区 cron 不支持原生指定）

### 六、与 WorkBuddy 内定时任务的关系

| 维度 | WorkBuddy 内定时任务 | GitHub Actions |
|---|---|---|
| 设备依赖 | 绑定本机（电脑开机 + 客户端在线） | **无关**，在 GitHub runner 上跑 |
| 投递渠道 | 智能体邮箱（账号级） | 自动 commit、Issue、邮件（自配 SMTP）、IM webhook |
| 触发时间 | 灵活（自然语言） | 标准 cron + 手动 |
| 修改配置 | 对话里改 prompt | push 新代码 |
| 适合场景 | 临时试探、快速试错 | **长期、稳定、需要换设备** |

可以两个并存：Actions 出周报作为权威来源，WorkBuddy 内任务留作手动触发的备用。
