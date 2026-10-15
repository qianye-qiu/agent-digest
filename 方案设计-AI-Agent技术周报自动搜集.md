# AI Agent 技术周报自动搜集方案（可落地版 v1.0）

> 运行环境：{{运行环境}}（推荐 GitHub Actions，备选 服务器 cron / Airflow）  
> 编程语言：{{编程语言}}（推荐 Python 3.11）  
> 推送渠道：{{推送渠道}}（推荐 邮件 + GitHub Issue 归档 双通道）  
> LLM 摘要服务：{{LLM服务}}（可选，不配置则降级为抽取式摘要）

---

## 0. 一分钟概览

每周一自动从 **论文 / 开源框架 / 官方博客 / 社区实践** 四类来源抓取近 7 天的 AI Agent 技术资讯，  
经过 **时间过滤 → 相关性打分 → 去重 → 可信度标注 → 分层配额** 五道流水线，  
产出一份 15–25 条的 Markdown 技术周报，按 **{{推送渠道}}** 推送，并归档到仓库供全文检索。  
每条资讯强制携带 **可信度评级（A+ ~ D）**，周报末尾附 **本周技术雷达 + 学习路线建议**。

---

## 1. 任务目标与非目标

### 1.1 目标（要做）

| 编号 | 目标                               | 验收标准                               |
| -- | -------------------------------- | ---------------------------------- |
| G1 | 覆盖近 7 天 Agent 领域新技术、框架更新、论文、工程实践 | 每周 ≥ 15 条，覆盖 ≥ 4 个栏目               |
| G2 | 面向开发人员，技术向                       | 每条含"技术要点 + 为什么重要 + 可复现链接"，无营销/融资内容 |
| G3 | 每条标注可信度                          | 100% 条目带评级标签与判定依据                  |
| G4 | 给出学习转化建议                         | 周报含"本周技术雷达 + 3 个动手任务"              |
| G5 | 零人工干预可运行，可回溯                     | 全量原始抓取落盘，周报可 diff，失败自动告警           |

### 1.2 非目标（明确不做）

- 不做融资/股价/人事/产品发布会新闻（除非含技术细节，如新模型架构说明）
- 不做全文翻译，只做中文要点摘要（≤ 80 字/条）
- 不做实时推送（周更即可），不做社交舆论情感分析
- 不整站镜像抓取，只取元信息（标题、摘要、URL、时间、作者/组织）

### 1.3 受众画像

后端 / 算法 / 应用工程师，1–5 年经验，正在或即将落地 Agent 应用。  
关心：**能不能用、怎么用、坑在哪、要不要升级**；不关心概念科普。

---

## 2. 触发方式与调度选型

### 2.1 方案对比

| 调度工具                   | 成本                  | 运维 | 优点                                                     | 缺点                                                                 | 适用场景                      |
| ---------------------- | ------------------- | -- | ------------------------------------------------------ | ------------------------------------------------------------------ | ------------------------- |
| **GitHub Actions（推荐）** | 公有仓免费；私有仓 2000 分钟/月 | 极低 | 无服务器、与代码同仓、Secrets 管理、Artifacts 归档、天然支持"写 Issue/PR 沉淀" | cron 按 UTC 且**不保证准点（常延迟 5–30 min）**；仓库 **60 天无活动会自动停用定时 workflow** | 团队已在 GitHub / Gitee，追求零运维 |
| 服务器 cron               | 已有机器的边际成本           | 中  | 完全可控、时区自由、可跑长任务                                        | 需自管机器、日志、告警、依赖；机器宕机即漏跑                                             | 内网环境、数据不出域                |
| Airflow / Dagster      | 高                   | 高  | 依赖编排、回填（backfill）、重试策略完善、可观测                           | 需维护集群；为周级任务过度设计                                                    | 已有数据平台，需与数仓任务编排           |
| 云函数 + 定时触发器            | 极低                  | 低  | 按需计费、免运维                                               | 超时限制（常见 ≤ 15 min）、本地调试麻烦                                           | 云上轻量部署                    |
| GitLab CI schedule     | 低                   | 低  | 与 GitLab 仓库一体化                                         | 与 Actions 类似的调度抖动                                                  | 自建 GitLab / 内网代码平台        |

### 2.2 推荐方案：**GitHub Actions 为主 + 人工 `workflow_dispatch` 兜底**

**选型理由**

1. **零基础设施**：周级任务只需要每周几分钟算力，为其维护一台服务器不划算。
2. **沉淀即产出**：周报可直接以 Markdown 提交回仓库 / 开 Issue，天然形成可检索的技术档案库（`git log`、`grep`、GitHub 搜索全可用），这是邮件推送做不到的。
3. **凭据安全**：Slack / 钉钉 / SMTP 等 Webhook 统一放 `Settings → Secrets`，不进代码库。
4. **失败可见**：workflow 失败自动发邮件通知，配合 Actions 运行日志，排查链路比裸 cron 短得多。
5. **可平滑迁移**：核心逻辑全在 `src/digest.py`，调度层只是壳，之后换 cron/Airflow 只改 20 行。

**必须注意的两个坑**

- Actions 的 cron 只支持 **UTC**，且高峰期会排队延迟 → 表达式不要写在整点，且时间窗留缓冲。
- 仓库 **60 天无任何活动**时 GitHub 会静默停用 scheduled workflow → 缓解办法：  
  (a) 周报本身会 commit 回仓库，天然保持活跃（推荐）；  
  (b) 或用外部 cron 定期调用 `workflow_dispatch` API 保活。

### 2.3 调度配置

```cron
17 2 * * 1        # 每周一 UTC 02:17 = 北京时间 周一 10:17
```

- 选 02:17 而非 02:00：避开 Actions 整点排队高峰。
- 覆盖上一个周一到本周一，跨周末完整覆盖 arXiv / GitHub 更新。
- 单次运行预算 ≤ 10 分钟；超时视为异常并告警。

### 2.4 时间窗定义（防漏与防重）

```
T            = 任务实际运行时刻（UTC）
窗口起点     = T - 8d     # 7 天 + 1 天重叠，防跨源时区/更新滞后导致漏抓
窗口终点     = T
去重缓存窗口 = 14d        # state/seen.json 记录已推送 URL，重叠部分靠它剔除
```

---

## 3. 数据来源清单

> **首次运行前必须执行 `python src/digest.py --check-sources`**：批量校验所有 URL 是否 200、RSS 是否可解析。  
> RSS 地址变动频繁，校验结果写入周报末尾"数据健康"栏，失效源自动降级并提醒维护。

### 3.1 A 组 · 学术论文（一手，可信度基准 4–5）

| 来源                       | 获取方式     | 接口 / 地址                                                                                                                                  | 说明                                                              |
| ------------------------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| arXiv                    | Atom API | `http://export.arxiv.org/api/query?search_query=cat:cs.AI+AND+abs:%22agent%22&sortBy=submittedDate&sortOrder=descending&max_results=100` | 也可用 `http://export.arxiv.org/rss/cs.AI`、`cs.CL`、`cs.MA`、`cs.SE` |
| HuggingFace Daily Papers | REST     | `https://huggingface.co/api/daily_papers`                                                                                                | 返回 `publishedAt`、`paper.title/summary/upvotes`，热度信号好用           |
| Semantic Scholar（可选）     | REST     | `https://api.semanticscholar.org/graph/v1/paper/search?query=LLM+agent&fields=title,abstract,publicationDate,citationCount`              | 用于补引用数/期刊信息，需 {{S2_API_KEY}}                                    |
| Papers with Code（可选）     | REST     | `https://paperswithcode.com/api/v1/papers/?q=agent`                                                                                      | 带代码实现的论文优先收录                                                    |

### 3.2 B 组 · 开源与框架（一手，可信度基准 4–5）

| 来源                   | 获取方式        | 接口 / 地址                                                                                         |
| -------------------- | ----------- | ----------------------------------------------------------------------------------------------- |
| GitHub 新仓库           | REST Search | `https://api.github.com/search/repositories?q=agent+created:>{DATE}&sort=stars&order=desc`      |
| GitHub 活跃仓库          | REST Search | `https://api.github.com/search/repositories?q=agent+pushed:>{DATE}&sort=updated`                |
| GitHub Releases（白名单） | REST        | `https://api.github.com/repos/{owner}/{repo}/releases?per_page=5`                               |
| GitHub Trending（可选）  | HTML 抓取     | `https://github.com/trending?since=weekly`（无官方 API；或用 {{Trending_API}}，需自行评估稳定性与 robots.txt 合规） |
| PyPI 版本更新            | REST        | `https://pypi.org/pypi/{package}/json`（读 `releases` 的 `upload_time`）                            |

**Release 白名单（Tier-1 框架，必抓）**

```
langchain-ai/langgraph, langchain-ai/langchain, run-llama/llama_index,
microsoft/autogen, crewAIInc/crewAI, microsoft/semantic-kernel,
pydantic/pydantic-ai, openai/openai-agents-python, google/adk-python,
modelcontextprotocol/servers, modelcontextprotocol/python-sdk,
browser-use/browser-use, agno-agi/agno, huggingface/smolagents,
stanfordnlp/dspy, All-Hands-AI/OpenHands, microsoft/playwright-mcp
```

### 3.3 C 组 · 官方博客与标准（一手，可信度基准 5）

| 来源                                 | 地址                                                                         | 备注                      |
| ---------------------------------- | -------------------------------------------------------------------------- | ----------------------- |
| OpenAI News / 官方博客                 | `https://openai.com/blog/rss.xml`（待校验）                                     | 模型/Agents SDK 更新        |
| Anthropic Engineering              | `https://www.anthropic.com/engineering`（RSS 待校验，无则抓 HTML 列表）               | Claude Code / Agent 实践  |
| Google DeepMind Research           | `https://deepmind.google/blog/rss.xml`（待校验）                                |                         |
| MCP 官方                             | `https://modelcontextprotocol.io` + `modelcontextprotocol/servers` Release | 协议变更必跟                  |
| LangChain Blog                     | `https://blog.langchain.dev/rss/`                                          |                         |
| LlamaIndex Blog                    | `https://www.llamaindex.ai/blog/rss.xml`                                   |                         |
| Microsoft / Azure AI Blog          | 官方 RSS                                                                     | Semantic Kernel、AutoGen |
| Cloudflare / Vercel / Netlify 工程博客 | RSS                                                                        | Agent 运行时与边缘部署          |

> 中文一手源：`{{中文官方源}}`，如云厂商 Agent 平台技术博客（阿里云/腾讯云/火山引擎），按需补充。

### 3.4 D 组 · 社区与实践（二手，可信度基准 2–3）

| 来源                            | 接口                                                                                                     | 权重                     |
| ----------------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------- |
| Hacker News                   | `https://hn.algolia.com/api/v1/search_by_date?query=agent&tags=story&numericFilters=created_at_i>{TS}` | 按 points 排序，≥ 50 分才进候选 |
| Reddit r/LLMDevs、r/LocalLLaMA | `https://www.reddit.com/r/{sub}/new.rss`                                                               | 低权重，需一手链接佐证            |
| InfoQ 中文 / 机器之心 / 量子位         | RSS（稳定性差，需在 `sources.yaml` 中标记 `optional: true`）                                                       | 仅当正文含一手链接时上调可信度        |
| Dev.to / Medium tag=ai-agent  | RSS / tag feed                                                                                         | 最低权重                   |

### 3.5 合规与礼仪（硬性）

- 遵守 `robots.txt`；设置明确 `User-Agent: AgentDigestBot/1.0 (+{{联系邮箱}})`
- 只抓列表/元信息，不做正文全量镜像
- GitHub 未认证 60 次/小时、认证后 5000 次/小时 → **必须配置 `{{GITHUB_TOKEN}}`**
- 单源并发 ≤ 2，请求间隔 ≥ 1s，超时 10s，失败指数退避重试 3 次
- 单源失败不影响整体（隔离降级，记录到"数据健康"栏）

---

## 4. 抓取与筛选逻辑

### 4.1 时间过滤规则（"近一周"判定）

```python
# 时间字段优先级（按来源类型逐层 fallback）
TS_FIELDS = {
    "arxiv":   ["published", "updated"],
    "rss":     ["published_parsed", "updated_parsed"],
    "github_repo":    ["created_at"],        # 新仓库看创建时间
    "github_release": ["published_at"],
    "github_push":    ["pushed_at"],         # 活跃仓库看推送时间
    "hn":      ["created_at_i"],
    "pypi":    ["upload_time"],
}

def resolve_ts(item, now):
    for f in TS_FIELDS[item.source_type]:
        v = item.get(f)
        if v: return parse_utc(v), "declared"
    return now, "inferred"          # 无时间戳：用抓取时刻，并标记
```

规则：

1. **统一 UTC** 存储与比较，展示时转 `Asia/Shanghai`。
2. 只保留 `窗口起点 ≤ ts ≤ 窗口终点` 的条目。
3. 允许 **未来 ≤ 24h** 的时间戳（源端时钟偏移）视为有效。
4. 时间戳缺失 → 用抓取时刻，条目标记 `ts_source=inferred`，**可信度上限压到 B**。
5. 跨源合并时以**最早**的首次出现时间为准（论文 arXiv 首发时间优先）。

### 4.2 相关性判定

**（1）关键词分层**

```yaml
CORE (核心, 必须命中 ≥1):
  [agent, agents, agentic, "multi-agent", "llm agent", 智能体, "tool use",
   "function calling", "tool calling", mcp, "model context protocol",
   "computer use", autonomous, "long-horizon", "agent harness"]

FRAME (框架, w=3):
  [langgraph, langchain, llamaindex, autogen, crewai, "semantic kernel",
   "pydantic-ai", "agents sdk", "google adk", dspy, smolagents, mastra,
   agno, "browser-use", "openhands", "claude code", "mcp server", a2a,
   langfuse, langsmith, phoenix, "arize"]

TOPIC (主题, w=1):
  [planning, memory, reflection, orchestration, routing, handoff,
   evaluation, benchmark, guardrail, sandbox, observability, tracing,
   "context engineering", "context window", rag, finetune, rl, verifier,
   "self-evolve", "prompt injection", jailbreak, latency, cost, "kv cache",
   idempotency, retry, "human-in-the-loop", "rate limit", streaming]

NEG (噪声, w=-5):
  [招聘, hiring, 股价, 融资, funding, 估值, 发布会, "ai 取代", 课程,
   培训班, 抽奖, 营销, 广告, "prompt 变现", crypto, "airdrop"]
```

**（2）打分公式**

```
score = 6 * |CORE ∩ title|
      + 3 * |CORE ∩ body|
      + 3 * |FRAME ∩ (title+body)|
      + 1 * |TOPIC ∩ (title+body)|
      - 5 * |NEG ∩ (title+body)|
      + 2 * (有可复现代码/仓库链接)
      + 2 * (来源 Tier-1)

收录条件： |CORE| ≥ 1  AND  score ≥ 6  AND  NEG 命中数 == 0
```

**（3）栏目归类**（按命中权重最高的维度）

`框架与工具更新` / `论文与算法` / `协议与标准(MCP·A2A)` / `工程实践与案例` /  
`评测·可观测·安全` / `其他值得一看`

### 4.3 去重策略（三级）

| 级别        | 方法                                                 | 阈值                       |
| --------- | -------------------------------------------------- | ------------------------ |
| L1 URL 归一 | 去 `utm_*`、`?ref=`、尾斜杠、http/https 归一、小写 host + path | 完全相同即丢弃                  |
| L2 标题相似   | 标题小写去标点 → 3-gram Jaccard 或 SimHash 汉明距离            | 相似度 ≥ 0.85 视为重复，保留可信度更高者 |
| L3 实体合并   | 论文按 arXiv ID / DOI；框架按 `{repo}@{version}`          | 多源互证 → 可信度 +1，合并展示"多源报道" |
| L4 历史去重   | `state/seen.json` 保存 14 天内已推送的 URL + 标题指纹          | 命中即丢弃                    |

### 4.4 分层与配额（控制信息密度）

| 层         | 判定                                  | 配额                        |
| --------- | ----------------------------------- | ------------------------- |
| **S 必读**  | Tier-1 框架 Release / 权威机构论文 / 协议标准变更 | 不限，通常 3–6 条               |
| **A 值得看** | score ≥ 10 或 HN ≥ 100 分             | ≤ 10 条                    |
| **B 扫一眼** | 6 ≤ score < 10                      | ≤ 6 条                     |
| **总计**    |                                     | **15–25 条**，超出则按 score 截断 |

### 4.5 可信度标注规则（强制字段）

**评级定义**

| 级别    | 标签        | 含义                              | 典型来源                         |
| ----- | --------- | ------------------------------- | ---------------------------- |
| ★★★★★ | `A+ 官方一手` | 官方发布 / 官方文档 / 官方 Release / 论文原文 | 厂商博客、GitHub Release、arXiv 原文 |
| ★★★★  | `A 高`     | 同行评议论文、顶会、权威技术媒体有原文直链           | 顶会论文、一手链接完备的深度报道             |
| ★★★   | `B 中`     | 知名开发者博客、社区高票讨论、二手技术报道           | HN 高票、InfoQ 有原文链接、Reddit 一手贴 |
| ★★    | `C 低`     | 聚合媒体 / 自媒体转述 / 无一手链接            | 公众号转载、无来源的"据称"               |
| ★     | `D 存疑`    | 无法核验来源、疑似 AI 批量生成、纯营销           | **默认不收录**，仅记入"已过滤"统计         |

**计算方式**

```
base:        官方一手 5 / 顶会论文 5 / 预印本论文 4 / 知名社区 3 / 聚合媒体 2 / 自媒体 1
evidence:    含官方或论文直链 +1；含可复现仓库或数据集 +1；仅二手转述 -1
consistency: ≥2 个独立来源互证 +1；单一来源 0；时间戳缺失 -1
cred = clamp(base + evidence + consistency, 1, 5)
映射 → 5:A+ / 4:A / 3:B / 2:C / 1:D

特殊封顶：预印本(preprint) 上限压到 4(A)，
仅当"≥2 源互证 且 有可复现代码"时才允许 5 —— 避免未经评议的论文被当成定论。
（该规则已在 src/digest.py: credibility() 实现，并有 tests/smoke_test.py 断言覆盖）
```

**强制附加标记**

- 所有 arXiv 条目加 `（预印本，未经同行评议）`
- `ts_source=inferred` 条目加 `（时间由抓取时刻推定）`
- 周报顶部固定声明：**「可信度为规则自动标注，重要决策前请人工复核原文」**
- 每条必须给出 `可信度依据`（一句话，如"官方 Release 页 + 版本号 v0.2.3"）

### 4.6 摘要生成（双模）

- **主模式（配置 {{LLM服务}} 时）**：输入标题 + 原文前 3000 字 → 输出  
  `{要点(≤80字)}` / `{技术关键词[]}` / `{为什么重要(≤40字)}` / `{建议动作}`；  
  温度 0.2，单条 ≤ 800 output tokens，批量 10 条/次。
- **降级模式（无 LLM / 调用失败）**：抽取式——取摘要首句 + 结论句，标题直译，  
  条目加 `（自动摘要，未润色）`，不影响推送。
- **硬要求**：LLM 不得编造链接、版本号、数字；未出现在原文的信息一律不写。

---

## 5. 汇总与推送

### 5.1 周报格式（Markdown 模板）


```markdown
# AI Agent 技术周报 · 2026-W42（10.08 – 10.15）

> 本期 21 条 | 覆盖窗口 UTC 2026-10-08 ~ 2026-10-15 | 抓取源 14/16 健康
> ⚠️ 可信度为规则自动标注，重要决策前请人工复核原文。

## 🔥 本周速览（TL;DR）
1. **LangGraph v0.4 发布**：新增 X，破坏性变更 Y → 升级需改 Z（可信度 ★★★★★ A+）
2. **MCP 规范 2025-xx 修订**：Streamable HTTP 取代 SSE（★★★★★ A+）
3. arXiv:2601.xxxxx《...》：多智能体记忆共享方案，在 X benchmark 提升 N%（★★★★ A，预印本）

## 🧩 框架与工具更新
### 1. LangGraph v0.4.0
- **来源**：github.com/langchain-ai/langgraph/releases | 2026-10-11
- **可信度**：★★★★★ A+（官方 Release 页，含版本号与 changelog）
- **要点**：...（≤80 字）
- **为什么重要**：...
- **开发建议**：升级前先看 migration guide；重点看第 3 条破坏性变更
- **链接**：[Release](...)  [Changelog](...)

（每条同构，栏目内按 score 降序）

## 📄 论文与算法
## 🔌 协议与标准（MCP / A2A / Function Calling）
## 🛠 工程实践与案例
## 🔍 评测 · 可观测 · 安全

## 📚 本周技术雷达（建议重点学习）
| 优先级 | 技术点 | 为什么 | 上手方式 | 产出物 |
|---|---|---|---|---|
| P0 | MCP Server 开发 | 工具生态正在标准化 | 用官方 SDK 写一个内部系统 MCP Server | 可复用工具包 |
| P1 | Agent 评测与回归 | 无评测即不可交付 | 搭 20 条用例集 + Langfuse 追踪 | 评测流水线 |
| P2 | 长上下文与记忆策略 | 长程任务瓶颈 | 复现论文 X 的记忆压缩方案 | 对比压测报告 |

## 🎯 本周三个动手任务
1. [2h] 用 MCP SDK 把团队内部 API 封装成 MCP Server，接入现有 Agent
2. [3h] 精读 arXiv:2601.xxxxx，跑通官方 repo 的最小示例
3. [1h] 给本期某一个开源项目提一个 issue 或文档 PR

## 🩺 数据健康
- 失效源：InfoQ RSS（HTTP 404）、DeepMind RSS（超时）→ 需维护
- 本期过滤：噪声 37 条、重复 12 条、低可信度 5 条
- 生成时间：2026-10-15 10:17 (UTC+8) | 耗时 3m21s
```

### 5.2 推送渠道对比与选型

| 渠道 | 接入方式 | 优点 | 缺点 | 适合 |
|---|---|---|---|---|
| **邮件（推荐主通道）** | SMTP（`smtplib`）/ 企业邮件 API | 人人有、可归档、支持长文与 HTML、可加回执统计 | 需配 SMTP 凭据；可能被判垃圾邮件 | 全员周更 |
| **GitHub Issue（推荐归档通道）** | `gh issue create` / REST | 可检索、可评论讨论、形成知识库 | 不主动触达 | 沉淀与检索 |
| Slack / 飞书 / 钉钉 / 企业微信机器人 | Incoming Webhook（Markdown 卡片） | 即时触达、可 @ 人、互动好 | 正文长度受限（需摘要版 + 全文链接） | 团队即时阅读 |
| RSS / 静态站点 | 生成 `feed.xml` + GitHub Pages | 订阅自由、可公开 | 触达弱 | 对外输出 |
| Notion / 腾讯文档 / Confluence | API 写入 | 与知识库打通 | 需额外授权与维护 | 已用该知识库 |

**推荐组合**：`{{推送渠道}}` = **邮件（全文）+ {{即时通讯渠道}}（摘要卡片 + 全文链接）+ GitHub Issue（归档）**
三者共用同一份 Markdown，只是渲染层不同（Jinja2 三套模板）。

### 5.3 归档与检索

```
archive/
  2026/2026-W42.md          # Markdown 周报
  2026/2026-W42.json        # 结构化原始条目（含 score/cred/来源）
  2026/2026-W42.raw.json    # 全量抓取快照（用于审计与回溯重放）
state/seen.json             # 14 天去重缓存
```
原始快照保留 **180 天**，支持"回溯重放"：换打分规则后可离线重算历史周报做对比。

---

## 6. 关键实现步骤与伪代码

### 6.1 目录结构

```
agent-digest/
├── .github/workflows/weekly-digest.yml
├── config/sources.yaml          # 来源清单（可增删，不改代码）
├── config/keywords.yaml         # 关键词分层与权重
├── src/digest.py                # 主流程
├── src/fetchers/{arxiv,github,rss,hn,pypi}.py
├── src/{filter,rank,dedupe,summarize,render,deliver}.py
├── templates/{markdown.md.j2,email.html.j2,im_card.md.j2}
├── state/seen.json
├── archive/                     # 自动生成
└── README.md
```

### 6.2 主流程伪代码

```python
def main(mode="run"):
    cfg   = load_config("config/")
    now   = datetime.now(timezone.utc)
    win   = (now - timedelta(days=8), now)        # 7d + 1d 重叠

    # 1) 抓取：多源并发，单源失败隔离
    raw = []
    for src in cfg.sources:                        # 并发度 4
        try:
            raw += FETCHERS[src.type](src, win)
        except Exception as e:
            log_source_error(src, e)               # 记入数据健康，继续

    save_snapshot(raw, f"archive/{iso_week}/raw.json")

    # 2) 时间过滤
    items = [i for i in raw if win[0] <= resolve_ts(i, now)[0] <= win[1]]

    # 3) 相关性打分 + 噪声剔除（必须命中 >=1 个 CORE 词）
    items = [i for i in items if (i.score := relevance(i)) >= 6]
    items = [i for i in items if not hit_any(i, cfg.neg)]

    # 4) 三级去重 + 历史去重
    items = dedupe(items)                          # URL / 标题指纹 / 实体合并
    items = [i for i in items if not seen_before(i, "state/seen.json", 14)]

    # 5) 可信度标注
    for i in items:
        i.cred, i.cred_reason = credibility(i)     # 见 4.5
    items = [i for i in items if i.cred >= 2]      # 剔除 D 级

    # 6) 分层配额 + 栏目归类
    picked = quota(items)                          # S 全收 / A<=10 / B<=6 / 总 15-25

    # 7) 摘要（LLM 优先，失败降级抽取式）
    for i in picked:
        i.summary = llm_summarize(i) or extractive(i)

    # 8) 学习建议（基于本期条目命中的 TOPIC 词频自动生成 + 固定雷达兜底）
    radar = build_learning_radar(picked)

    # 9) 渲染 + 推送 + 归档
    md = render("templates/markdown.md.j2", picked, radar, health_report())
    deliver(md, cfg.push)                          # {{推送渠道}}
    archive(md, picked, raw)
    update_seen(picked)
```

### 6.3 关键函数片段

```python
# —— 相关性打分 ——
def relevance(it):
    t, b = it.title.lower(), (it.body or "").lower()
    s  = 6 * hit(t, CORE) + 3 * hit(b, CORE)
    s += 3 * hit(t + " " + b, FRAME)
    s += 1 * hit(t + " " + b, TOPIC)
    s -= 5 * hit(t + " " + b, NEG)
    s += 2 * bool(it.repo_url or it.code_url)
    s += 2 * (it.source_tier == 1)
    return s

# —— 可信度 ——
def credibility(it):
    base = {"official":5, "venue":5, "preprint":4, "community":3,
            "media":2, "selfmedia":1}[it.source_class]
    ev  = 0
    ev += 1 if it.official_url or it.paper_url else 0
    ev += 1 if it.repo_url or it.dataset_url else 0
    ev -= 1 if it.is_secondhand else 0
    cons = 1 if it.cross_source_count >= 2 else (0 if it.cross_source_count == 1 else -1)
    if it.ts_source == "inferred": cons = min(cons, 0)
    score = max(1, min(5, base + ev + cons))
    return score, f"来源类型={it.source_class}({base}) 证据链{ev:+d} 互证{cons:+d}"

# —— 去重 ——
def norm_url(u):
    p = urlparse(u); q = {k:v for k,v in parse_qsl(p.query) if not k.startswith("utm_")}
    return urlunparse(("", "", p.netloc.lower(), p.path.rstrip("/"), urlencode(q), ""))

def title_fp(t):
    return simhash(re.sub(r"[^\w\s]", "", t.lower()))

def is_dup(a, b):
    return norm_url(a.url) == norm_url(b.url) or hamming(title_fp(a.title), title_fp(b.title)) <= 3

# —— 配额 ——
def quota(items):
    S = [i for i in items if i.tier == "S"]
    A = sorted([i for i in items if i.score >= 10 and i.tier != "S"], key=lambda x: -x.score)[:10]
    B = sorted([i for i in items if 6 <= i.score < 10], key=lambda x: -x.score)[:6]
    out = S + A + B
    return sorted(out, key=lambda x: (-x.tier_rank, -x.score))[:25]
```

### 6.4 GitHub Actions 配置（核心片段）

```yaml
name: weekly-agent-digest
on:
  schedule:
    - cron: '17 2 * * 1'      # 每周一 UTC 02:17 = 北京 10:17
  workflow_dispatch:           # 手动补跑 / 保活

jobs:
  digest:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions: { contents: write, issues: write }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11', cache: 'pip' }
      - run: pip install -r requirements.txt

      - name: Run digest
        env:
          GITHUB_TOKEN:   ${{ secrets.GH_TOKEN }}
          LLM_API_KEY:    ${{ secrets.LLM_API_KEY }}
          SMTP_HOST:      ${{ secrets.SMTP_HOST }}
          SMTP_USER:      ${{ secrets.SMTP_USER }}
          SMTP_PASS:      ${{ secrets.SMTP_PASS }}
          IM_WEBHOOK:     ${{ secrets.IM_WEBHOOK }}        # 钉钉/飞书/Slack {{推送渠道}}
          MAIL_TO:        ${{ secrets.MAIL_TO }}
        run: python src/digest.py --window 8d --push {{推送渠道}}

      - name: Archive & commit
        run: |
          git config user.name "agent-digest-bot"
          git add archive state
          git commit -m "chore: digest $(date -u +%G-W%V)" || echo "no changes"
          git push

      - name: Open archive issue
        if: always()
        env: { GH_TOKEN: ${{ secrets.GH_TOKEN }} }
        run: gh issue create --title "Agent 周报 $(date -u +%G-W%V)" --body-file archive/latest.md --label digest

      - name: Alert on failure
        if: failure()
        run: curl -X POST -H 'Content-Type: application/json' \
             -d '{"msgtype":"text","text":{"content":"⚠️ Agent 周报任务失败，请查看 Actions 日志"}}' \
             "$IM_WEBHOOK"
```

**依赖**：`requests`、`feedparser`、`PyYAML`、`Jinja2`、`tenacity`（重试）、`simhash` 或自实现：`requirements.txt` 锁定版本。

### 6.5 落地步骤（按顺序，约半天可跑通）

| 步骤 | 动作 | 产出 | 耗时 |
|---|---|---|---|
| 1 | 定运行环境/语言/推送渠道，填占位符 | 决策记录 | 15 min |
| 2 | 建仓，放 `sources.yaml` + 跑 `--check-sources` | 有效源清单 | 30 min |
| 3 | 实现 fetchers（先 RSS + arXiv + GitHub 三类） | 原始快照 | 2–3 h |
| 4 | 实现 filter/rank/dedupe，本地 dry-run 看命中率 | 打分日志 | 2 h |
| 5 | 接 {{LLM服务}} 摘要 + 降级路径 | 摘要样本 | 1 h |
| 6 | 渲染模板 + {{推送渠道}} 打通（先发自己） | 首份周报 | 1 h |
| 7 | 配 Actions 定时 + 失败告警 | 自动化 | 30 min |
| 8 | 连续 2 周人工校准关键词与阈值（调 `score>=6`、配额） | 调优后的 `keywords.yaml` | 1 h |

---

## 7. 面向开发人员的学习提升设计

### 7.1 Agent 技术雷达（周报据此生成本周重点）

| 层级 | 技术点 | 学习对象 | 检验方式 |
|---|---|---|---|
| **协议层** | MCP、A2A、Function Calling / Tool Schema、OpenAPI for Agents | 规范原文 + 官方 SDK | 手写一个 MCP Server 并被两个客户端调用成功 |
| **编排层** | LangGraph / AutoGen / CrewAI / Semantic Kernel / Pydantic AI / ADK | 官方 Quickstart + 源码中状态机部分 | 用状态机实现一个含"重试 + 人工审批"分支的流程 |
| **能力层** | 规划与分解、记忆（短期/长期/压缩）、工具调用、多智能体协作与路由、自我反思 | 本期论文 + 框架实现 | 设计一个 3 智能体协作任务并跑通 |
| **工程层** | 评测集与回归、可观测（Langfuse/LangSmith/Phoenix）、成本与延迟优化、缓存与幂等、重试与降级、并发与流式 | 本期实践案例 | 给现有 Agent 加 20 条评测用例 + 全链路 trace |
| **安全层** | Prompt Injection 防护、最小权限、沙箱执行、敏感数据脱敏、Human-in-the-loop | 本期安全事故复盘 | 完成一次越权/注入红队测试并修复 |

### 7.2 每周学习 SOP（个人，约 5 小时/周）

```
周一 15min  读周报「本周速览 + 技术雷达」，圈出 1 个 P0 技术点
周三 2h     精读 1 篇论文（先读图表与实验，再看方法）+ 跑通官方 repo 最小示例
周四 2h     动手：把技术点用到自己的项目里（哪怕只是 PoC）
周五 30min  写 200 字笔记 → 团队知识库 / 自己的 blog（输入→输出闭环）
月末 1h     复盘：本月 4 个技术点是否进入生产？没进入的原因是什么？
```

团队版：每周 30 分钟「周报共读会」，轮流讲 1 条；季度沉淀为内部 Agent 开发规范。

### 7.3 12 周能力提升路线（建议跟着周报节奏走）

| 周次 | 主题 | 产出物 |
|---|---|---|
| W1–2 | 工具调用与 MCP：把内部 API 变成标准工具 | 1 个可复用 MCP Server |
| W3–4 | 编排与状态机：从"链式调用"到"图/状态机" | 带重试与人工审批的编排 demo |
| W5–6 | 记忆与上下文工程：压缩、检索、长期记忆 | 长程任务对比压测报告 |
| W7–8 | 多智能体：角色拆分、路由、handoff、冲突消解 | 3 智能体协作 PoC |
| W9–10 | 评测与可观测：离线 eval + 在线 trace | 评测流水线 + 看板 |
| W11–12 | 安全与成本：注入防护、权限、缓存、模型分级路由 | 安全检查清单 + 成本优化报告 |

### 7.4 能力升级的 5 个台阶（自测定位）

1. **会用**：能调 API 拼出一个 Demo
2. **会调**：懂上下文工程、提示结构化、输出约束、few-shot 设计
3. **会编排**：能把业务流程建模成状态机/多智能体，处理失败分支与人工介入
4. **会工程化**：有评测、有监控、有成本控制、有灰度与回滚——**这里是绝大多数人的瓶颈，也是周报最有价值的部分**
5. **会架构与治理**：权限模型、数据边界、合规审计、平台化复用

> 建议：周报「技术雷达」每期固定至少 1 条落在 **第 4 台阶（工程化）**，
> 因为框架更新迭代快但工程化能力不会过时。

---

## 8. 运维、成本与风险

**成本估算**

- 算力：GitHub Actions 公有仓免费；私有仓约 5 分钟/周 × 4 ≈ 20 分钟/月，远低于 2000 分钟额度。
- LLM 摘要：约 25 条 × 1.2k input + 200 output ≈ 35k tokens/周，按 {{LLM服务}} 计价约 **{{月成本}}**（可忽略）。
- 存储：原始 JSON 约 1–3 MB/期，一年 < 150 MB。

**健壮性**

- 单源失败隔离 + 3 次指数退避重试 + 10s 超时
- 幂等：同一周重跑不重复推送（`state/seen.json` + 周报文件已存在则跳过 ISSUE 创建）
- `--dry-run`（只落盘不推送）、`--backfill 2026-W40`（补跑历史周）两个开关必备
- 空结果保护：条目 < 8 条时视为异常，仍推送但标题加 `[数据异常]` 并告警

**风险与对策**

| 风险 | 对策 |
|---|---|
| RSS 地址失效 | 每次运行校验，失效源进"数据健康"栏并 @ 维护人 |
| GitHub API 限流 | 必须配 Token；结果缓存 6 小时 |
| arXiv API 偶发 5xx | 重试 + 备用 RSS |
| LLM 幻觉编造版本号/链接 | 摘要只输出原文出现的实体；渲染前用正则校验链接来自原始条目 |
| 信息茧房（只推熟悉框架） | `sources.yaml` 保留 20% 配额给"探索类来源"（随机新仓库 / 跨领域论文） |
| 60 天无活动导致 Actions 停用 | 周报自动 commit 保活；或用外部 cron 触发 `workflow_dispatch` |
| 推送凭据泄露 | 全部走 Secrets，禁止打印；`.env.example` 只放键名 |

**效果度量（可选，用于持续调优）**

- 覆盖率：本期命中来源数 / 总来源数
- 有效率：人工标记的"有用条目" / 总条目（目标 ≥ 60%）
- 阅读率：邮件打开率 或 IM 卡片点击数
- 每季度根据有效率调整 `keywords.yaml` 权重与收录阈值

---

## 9. 占位符清单（运行前必须填写）

| 占位符 | 说明 | 建议值 |
|---|---|---|
| `{{运行环境}}` | 调度与运行环境 | GitHub Actions（ubuntu-latest） |
| `{{编程语言}}` | 实现语言 | Python 3.11 |
| `{{推送渠道}}` | 推送目标 | 邮件（全文）+ {{即时通讯渠道}}（摘要卡）+ GitHub Issue（归档） |
| `{{即时通讯渠道}}` | Slack / 飞书 / 钉钉 / 企业微信 | 按团队现状 |
| `{{LLM服务}}` | 摘要模型 | {{LLM服务}}（不填则走抽取式降级） |
| `{{GITHUB_TOKEN}}` | GitHub API 凭据（必填，否则限流） | Secrets |
| `{{S2_API_KEY}}` | Semantic Scholar（可选） | — |
| `{{Trending_API}}` | GitHub Trending 第三方接口（可选） | — |
| `{{中文官方源}}` | 中文技术源补充（可选） | 云厂商 Agent 技术博客 |
| `{{联系邮箱}}` | User-Agent 与告警接收人 | — |
| `{{月成本}}` | LLM 与算力成本 | 待实测 |

---

## 10. 落地 Checklist

- [ ] 确定 `{{运行环境}}` / `{{编程语言}}` / `{{推送渠道}}`
- [ ] 建仓并提交 `config/sources.yaml`，运行 `--check-sources` 校验全部来源
- [ ] 实现 fetchers（RSS / arXiv / GitHub / HN / PyPI）
- [ ] 实现 filter → rank → dedupe → credibility → quota
- [ ] 接 `{{LLM服务}}` 摘要 + 抽取式降级
- [ ] 渲染 Markdown / 邮件 HTML / IM 卡片三套模板
- [ ] 打通 `{{推送渠道}}`，先发自己验证排版
- [ ] 配 Actions 定时 + 失败告警 + 自动 commit 保活
- [ ] 连续 2 周人工校准关键词权重与配额阈值
- [ ] 建立团队「周报共读」机制，形成学习闭环
