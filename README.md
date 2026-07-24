# AI Content Miner

> 从海量社交媒体信息中自动完成抓取、智能筛选、研报生成与企业微信推送的知识工作流。

## 项目定位

本项目解决的核心问题是：在信息过载的环境中，如何从大量低质量社交媒体内容中自动筛选高价值信息，并生成结构化研报。

### 平台处理边界

- 小红书和知乎使用 MediaCrawler，并进入规则、语义去重、互动质量和博主画像四层
  筛选。四层原始分数会正规化为 0–10 综合分，再生成逐条报告并推送企业微信。
- Twitter/X 使用独立流程：规则筛选、Embedding 多主题筛选、回复区筛选、
  极简摘要、分层标签、`data/processed/x.jsonl` 和 `reports/x.html`。
- Reddit 通过指定社区的 `new/.rss` 获取最新帖子，在本地执行关键词、时间窗口和
  帖子 ID 过滤，随后进入非 Twitter 的四层筛选与输出流程。
- 主入口对 Twitter 做显式路由；Twitter 流程不会误入小红书、知乎或 Reddit 流程。

### 适用场景

- AI Agent、量化投资、科技前沿等领域的每日信息聚合
- 研究团队自动生成行业简报
- 个人知识工作流自动化

## 功能列表

| 功能 | 说明 |
| --- | --- |
| 数据爬取 | 小红书、知乎使用 MediaCrawler；X 使用实验性的 twscrape；Reddit 使用 Atom/RSS。 |
| 四层筛选 | 非 Twitter 内容依次执行规则、语义去重、互动质量和博主画像筛选。 |
| 综合评分 | 将四层乘积分数正规化到 0–10；中性组合为 6 分，原始分数保留用于审计。 |
| Twitter 信息流 | 使用独立三层筛选、极简摘要、结构化 JSONL 和聚合页面。 |
| 多模式输出 | 短内容生成文本卡片（`.txt`）；中长内容生成完整 HTML 研报（`.html`）。 |
| 企业微信推送 | 使用 Markdown V2 格式推送消息，并附带在线阅读链接。 |
| RadIter 日志 | 记录每次决策过程，为后续持续优化提供依据。 |

## 快速开始

### 前置条件

- Python 3.9 或更高版本；使用 X/twscrape 时需要 Python 3.10 或更高版本
- [uv](https://docs.astral.sh/uv/)（用于安装并运行 MediaCrawler）
- OpenAI API Key，或兼容接口的 API Key
- 小红书或知乎流程需要企业微信机器人 Webhook；Twitter 通知默认关闭

### 1. 克隆项目

```bash
git clone https://github.com/kassidylee/ai-content-miner.git
cd ai-content-miner
```

### 2. 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

也可以用 `uv` 创建项目独立环境，避免影响系统 Python：

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

本项目与 MediaCrawler 使用相互独立的 Python 环境。本项目的
`requirements.txt` 只安装内容处理和推送依赖；MediaCrawler 依赖由其
`uv.lock` 管理，避免把两个项目的 Playwright、pandas 等版本混装。
twscrape 属于本项目依赖，当前固定为 `0.19.2`；其会话数据库和浏览器 Cookie 只保存在
实际运行任务的电脑上。Reddit RSS 使用 Python 标准库解析 Atom，并复用已有的
`requests`，不需要 OAuth、PRAW、登录 Cookie 或额外账号。

### 3. 配置项目

复制环境变量模板，并在本地 `.env` 中填写敏感配置：

```bash
cp .env.example .env
```

```dotenv
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=your-model-name

# 非 Twitter 流程必填；Twitter 仅在 TWITTER_ENABLE_WECOM=True 时必填。
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx
```

`.env` 已被 Git 忽略，不得提交。程序启动时会自动加载它；部署环境也可以直接导出
同名环境变量，且外部环境变量优先于 `.env`。

非敏感运行配置继续在 `config.py` 中维护：

```python
# 报告预览地址，必须可被企业员工访问
# 开发环境：http://127.0.0.1:8000/reports（仅本机可访问）
# 生产环境：请填写企业内部可访问的实际地址
REPORT_BASE_URL = "http://127.0.0.1:8000/reports"

# Twitter 通知默认关闭
TWITTER_ENABLE_WECOM = False
```

其他配置项请参阅 `config.py` 中的注释。

### 4. 配置 MediaCrawler

当前桥接器明确对齐 MediaCrawler commit
`c9a111be73586bdf6fc44536f088e4db6ed86d64`。在项目根目录克隆并安装：

```bash
git clone --recurse-submodules https://github.com/kassidylee/ai-content-miner.git
cd ai-content-miner

git submodule update --init --recursive
cd MediaCrawler
uv sync
cd ..

git checkout c9a111be73586bdf6fc44536f088e4db6ed86d64
uv sync
cd ..
```

该 MediaCrawler 版本要求 Python 3.11 或更高版本，`uv sync` 会按其
`pyproject.toml` 和 `uv.lock` 建立独立环境。MediaCrawler 首次运行通常需要扫码登录；
默认 CDP 模式还需要按其说明准备 Chrome。若 MediaCrawler 位于其他目录，请在
`config.py` 中设置绝对路径 `MEDIACRAWLER_PATH`。

### 5. 启动报告预览服务

```bash
python3 server.py
```

然后在浏览器中访问：

```text
http://127.0.0.1:8000/reports/
```

确认报告目录可以正常访问。

### 可选：测试 X 关键词采集

X 不经过 MediaCrawler。本分支使用 `twscrape==0.19.2` 的异步 `API.search()` 接口，
并把结果转换为项目已有的 JSONL 格式。2026-07-22 已使用一个专用账号完成一次最多
3 条结果的真实只读烟雾测试，搜索、JSONL 写入和下游解析均成功。该功能仍处于实验阶段；
一次验证成功不代表 X 非公开接口能够长期稳定。

先在浏览器中正常登录 X，然后打开浏览器开发者工具：

1. 在 Chrome 中按 `⌥⌘I`，打开 **Application**。
2. 在左侧选择 **Storage → Cookies → https://x.com**。
3. 分别找到 `auth_token` 和 `ct0`，只复制它们的 **Value**。
4. 不要把这些值发到聊天、截图或 GitHub；它们代表已登录会话。

运行本地会话创建脚本：

```bash
.venv/bin/python scripts/setup_twscrape_session.py
```

脚本只询问 X 用户名、`auth_token` 和 `ct0`，不会询问 X 密码。两个 Cookie 输入均不显示，
最终只写入 Git 已忽略的 `.local/x/twscrape.db`，并将文件权限设为仅当前用户可读写。
不同电脑不能通过 Git 同步该数据库，需要各自在本机创建。

随后只测试采集，不调用模型、不生成报告、不发送企业微信：

```bash
.venv/bin/python scripts/smoke_test_twscrape.py "AI Agent" --limit 3
```

烟雾测试成功后，才将 `config.py` 中的平台改为：

```python
CRAWL_PLATFORM = "x"
```

### 可选：测试 Reddit RSS 采集

Reddit 不经过 MediaCrawler。当前方案读取配置中明确社区的 `new/.rss`，再在本地按
关键词和最近 168 小时过滤。RSS 不提供帖子分数、点赞比例、评论数或 flair，程序会将
这些字段明确标记为不可用，不会编造互动数据。

只测试一个社区的 RSS 请求、Atom 解析和下游加载：

```bash
.venv/bin/python scripts/smoke_test_reddit_rss.py "model" \
  --subreddit LocalLLaMA --limit 3
```

烟雾测试成功后修改：

```python
CRAWL_PLATFORM = "reddit"
REDDIT_RSS_SUBREDDITS = ["LocalLLaMA"]
```

2026-07-24 当前开发机真实测试中，RSS 返回 HTTP 200，但响应额度约 30 秒才恢复一次。
默认只配置一个社区；多社区运行会根据响应头在请求之间等待，避免连续请求触发 429。
详见 [`docs/reddit-rss-collection.md`](docs/reddit-rss-collection.md)。

### 6. 运行完整工作流

```bash
python3 main.py --check-config
python3 main.py
```

`--check-config` 只检查必填配置和当前采集器。小红书、知乎会检查 MediaCrawler 路径、
commit 和运行解释器；X 会检查 twscrape 版本、本地会话数据库和已处理状态；Reddit
会检查社区列表、RSS 请求参数、User-Agent 和已处理状态，
不会启动爬虫、调用模型或发送企业微信消息。配置、爬虫退出码、当次无数据或推送
失败时，主程序均返回非零退出状态。

## 项目结构

```text
ai-content-miner/
├── config.py                   # 项目配置，不要提交真实凭证
├── main.py                     # 主入口，全自动流水线
├── server.py                   # 静态报告预览服务
├── requirements.txt            # Python 依赖
├── README.md                   # 使用说明
├── steps.sh                    # 一键部署脚本
│
├── analyzer/                   # 分析模块
│   ├── __init__.py
│   ├── filter.py               # 非 Twitter 四层筛选
│   ├── twitter_rules.py        # Twitter 第一层规则
│   ├── twitter_embedding.py    # Twitter 多主题语义筛选
│   ├── twitter_comments.py     # Twitter 回复区筛选
│   ├── twitter_enricher.py     # Twitter 摘要和标签
│   └── twitter_pipeline.py     # Twitter 三层筛选编排
│
├── crawler/                    # 爬虫模块
│   ├── __init__.py
│   ├── base.py                 # 采集器公共结果与接口
│   ├── factory.py              # 按平台选择采集器
│   ├── mediacrawler_bridge.py  # MediaCrawler 调度
│   ├── twscrape_bridge.py      # X 关键词搜索与本地去重
│   └── reddit_rss_bridge.py    # Reddit Atom/RSS 采集
├── scripts/
│   ├── setup_twscrape_session.py # 创建本地 Cookie 会话
│   ├── smoke_test_twscrape.py    # 只读 X 搜索烟雾测试
│   └── smoke_test_reddit_rss.py  # 只读 Reddit RSS 烟雾测试
│
├── output/                     # 输出模块
│   ├── __init__.py
│   ├── generator.py            # 文本卡片和 HTML 研报生成
│   └── twitter_feed.py         # Twitter 聚合页面
│
├── workflows/
│   └── twitter.py              # Twitter 独立工作流
│
├── notifier/                   # 推送模块
│   ├── __init__.py
│   └── wecom.py                # 企业微信推送与配置校验
│
├── utils/                      # 工具模块
│   ├── __init__.py
│   ├── parser.py               # 文章解析，唯一权威实现
│   └── raditer.py              # RadIter 决策日志
│
├── data/                       # 爬取数据，运行时自动创建
├── reports/                    # 生成的报告，运行时自动创建
├── logs/                       # 日志文件，运行时自动创建
└── articles/                   # 手动输入文章，可选
```

## 工作流程

```text
小红书、知乎：
MediaCrawler
  -> 本次运行内容文件加载与标准化
  -> 规则筛选
  -> 语义去重（提供对比样本时启用）
  -> 互动质量筛选
  -> 博主画像筛选
  -> 0–10 综合评分
  -> 输出生成
  -> 企业微信推送

Twitter/X：
twscrape
  -> Twitter 专用标准化
  -> Twitter 规则筛选
  -> Twitter 多主题 Embedding 筛选
  -> Twitter 回复区筛选
  -> 极简摘要与分层标签
  -> data/processed/x.jsonl
  -> reports/x.html
  -> 可选企业微信通知

Reddit：
指定 subreddit 的 new/.rss
  -> Atom 解析和正文清洗
  -> 本地关键词、时间窗口和 ID 过滤
  -> 本次运行 JSONL
  -> 非 Twitter 四层筛选与输出流程
```

每次 MediaCrawler 调用都通过 CLI 传入平台、关键词、数量限制、JSONL 格式和
独立输出目录，不会修改 MediaCrawler 的 `config/base_config.py`。当前下游不消费
评论数据，因此调用时明确关闭评论抓取。加载器只读取本次运行产生的
`<type>_contents_<date>.jsonl`，不会递归读取历史输出，也不会把 comments/creators
误当成文章。

twscrape 同样为每次执行建立独立输出目录，只读取该次搜索返回的数据。它按关键词调用
`Latest` 搜索，跨关键词按帖子 ID 去重，保留最近 168 小时的内容，再应用总数量上限。
已处理 ID 仅在完整处理和推送流程成功后写入本地状态；烟雾测试不会确认状态，因此可以
重复测试同一批帖子。

Reddit RSS 同样只读取本次运行的数据。一个社区暂时失败时会继续其他社区；全部社区
失败时本次运行返回失败。多社区之间默认至少等待 31 秒，并尊重响应中的限流重置时间。

## 输出模式

小红书、知乎和 Reddit 按内容字数选择输出格式：

| 内容字数 | 输出格式 | 说明 |
| --- | --- | --- |
| 少于 500 字 | 纯文本卡片（`.txt`） | 提取核心观点，不进行深度分析。 |
| 不少于 500 字 | 完整 HTML 研报（`.html`） | 包含评分卡、雷达图和深度精读。 |

中等长度内容（500 至 1500 字）和长内容（超过 1500 字）目前均生成完整 HTML 研报。

Twitter 不生成逐条研报。所有候选推文及筛选审计追加写入
`data/processed/x.jsonl`，最终保留项聚合展示在 `reports/x.html`，主链接直接跳转
原始推文。

### 短内容卡片示例

```text
### Agent 时代系统研究还能做什么

来源：小红书 | 评分：7.5/10
核心价值：探讨 AI Agent 时代系统研究的发展方向。

维度评分：
- 洞察深度：1.8/2
- 时效性：1.5/2
- 启发性：1.6/2

建议：本文为短内容，系统已提取核心观点。如需深度分析，建议查找原始出处。
```

### 完整 HTML 研报

字数不少于 500 字的内容将生成完整 HTML 研报，包含以下部分：

- 评分卡：SVG 雷达图和评分表，固定展示在报告顶部。
- 简报：包括背景、核心内容和一句话总结。
- 深度精读：包括观点拆解、技术细节、代码解析、应用场景和局限性分析。

## 配置说明

### 环境变量与 `config.py` 关键配置项

| 配置项 | 说明 | 示例 |
| --- | --- | --- |
| `LLM_API_KEY` | `.env` 中的 LLM API Key | `your-api-key-here` |
| `LLM_BASE_URL` | `.env` 中的 OpenAI 兼容 API 地址 | `https://api.openai.com/v1` |
| `LLM_MODEL_NAME` | `.env` 中由 API 服务商提供的实际模型 ID | `your-model-name` |
| `EMBEDDING_MODEL` | 非 Twitter 路线使用的实际 Embedding 模型 ID | `text-embedding-3-small` |
| `TWITTER_EMBEDDING_MODEL` | 启用 Twitter Embedding 后使用的模型 ID | `text-embedding-3-small` |
| `WECOM_WEBHOOK` | `.env` 中的企业微信 Webhook | `https://qyapi.weixin.qq.com/...` |
| `SCORE_THRESHOLD` | 四层正规化综合分阈值，范围 0–10 | `6.0` |
| `SEMANTIC_DEDUP_THRESHOLD` | 非 Twitter 语义重复判定阈值 | `0.85` |
| `COMMENT_PASS_THRESHOLD` | 非 Twitter 互动质量最低分 | `0.5` |
| `AUTHOR_PROFILE_THRESHOLD` | 非 Twitter 博主画像最低分 | `0.9` |
| `REPORT_BASE_URL` | 报告预览服务地址，必须可被员工访问 | `http://127.0.0.1:8000/reports` |
| `CRAWL_PLATFORM` | 爬取平台 | `xhs`、`zhihu`、`x`、`reddit` |
| `SEARCH_KEYWORDS` | 搜索关键词；X 建议使用带技术意图的组合查询 | `["\"AI Agent\" (framework OR benchmark)"]` |
| `MEDIACRAWLER_PATH` | MediaCrawler 仓库路径 | `./MediaCrawler` |
| `MEDIACRAWLER_COMMIT` | 已对齐并校验的 commit | `c9a111b...` |
| `MEDIACRAWLER_PYTHON` | 未使用 uv 时的 Python >=3.11 解释器，可留空 | `/path/to/python` |
| `TWSCRAPE_DB_FILE` | X 本地会话数据库，不得提交 | `.local/x/twscrape.db` |
| `TWSCRAPE_RESULTS_PER_QUERY` | 每个 X 关键词最多读取条数 | `50` |
| `TWSCRAPE_LOOKBACK_HOURS` | X 帖子的本地时间窗口 | `168` |
| `REDDIT_RSS_SUBREDDITS` | Reddit 明确社区列表 | `["LocalLLaMA"]` |
| `REDDIT_RSS_RESULTS_PER_SUBREDDIT` | 每个社区最多读取的 feed 条目 | `10` |
| `REDDIT_RSS_REQUEST_INTERVAL_SECONDS` | 多社区请求间隔 | `31` |
| `REDDIT_RSS_LOOKBACK_HOURS` | Reddit 本地时间窗口 | `168` |
| `TWITTER_RULE_FILTER` | 仅供 Twitter 使用的第一层规则 | 字典 |
| `TWITTER_EMBEDDING_ENABLED` | 是否启用 Twitter Embedding 第二层筛选 | `False` |
| `TWITTER_INTEREST_TOPICS` | Twitter Embedding 主题与独立阈值 | 列表 |
| `TWITTER_EMBEDDING_FILTER_MODE` | Twitter 语义筛选模式 | `shadow`、`enforce` |
| `TWITTER_COMMENT_FILTER` | Twitter 回复区筛选阈值 | 字典 |
| `TWITTER_TAG_TAXONOMY` | Twitter 受控分层标签 | 列表 |
| `TWITTER_ENABLE_WECOM` | 是否发送 Twitter 摘要通知 | `False` |

## 当前接入边界

- 主入口按平台分流。只有 X 调用 `workflows/twitter.py`；其他平台不会调用 Twitter
  专用规则、Embedding、回复区筛选或聚合页面。
- 小红书、知乎和 Reddit 使用非 Twitter 四层筛选。当前主入口没有加载历史对比样本，
  因此语义去重层会明确记录为跳过；规则、互动质量和博主画像层仍正常执行。
- 四层筛选保留原始乘积分数，并将中性组合映射为 6 分、最高组合映射为 10 分。
  `SCORE_THRESHOLD` 只与正规化后的 0–10 分比较。
- Lingzao、RAL 和旧 AI 评分器不再由主流程调用。
- 手动 `articles/` 加载不会在自动爬取流程中回退触发。
- MediaCrawler 的 `detail`、`creator` 参数尚未在本项目配置中接入，启动检查会明确
  拒绝这两种模式；当前只支持 `search`。
- 登录方式当前只接入 `qrcode`、`phone`；为避免凭证出现在命令日志或仓库配置中，
  本轮没有接入 cookie 参数。
- X 仅接入 twscrape 的只读关键词搜索，不包含发帖、点赞、关注、私信、账号池扩容、
  CAPTCHA 绕过或代理轮换。
- Reddit 仅低频读取配置社区的 `new/.rss`，不使用 OAuth、PRAW、登录 Cookie、
  搜索 feed 或代理轮换；RSS 不提供互动指标，访问规则变化或限流会使采集失败。
- twscrape 使用非公开 X GraphQL 接口，可能因 X 改版、Cookie 失效、限流或账号验证而
  中断；任何失败都会返回非零状态，不会显示为采集成功。
- X 使用独立三层筛选和结构化聚合页，不调用非 Twitter 四层筛选或逐条报告生成器。

## 常见问题

### Q1：MediaCrawler 爬取失败怎么办？

- 确认 `MEDIACRAWLER_PATH` 配置正确。
- 在 `MediaCrawler/` 目录中手动运行测试。
- 检查网络环境，确保 MediaCrawler 可以访问目标社交媒体平台。

### Q2：企业微信中的报告链接无法打开怎么办？

- 检查 `REPORT_BASE_URL` 是否配置为企业员工可访问的地址。
- 确认 `python3 server.py` 正在运行。
- 使用内网地址时，确认员工设备与服务器位于同一网络。
- 如需从公网访问，可使用 ngrok 等内网穿透工具。

### Q3：API 调用成本较高怎么办？

- 使用成本更低的模型，例如 `gpt-3.5-turbo` 或 `deepseek-chat`。
- 提高 `SCORE_THRESHOLD`，减少进入输出环节的非 Twitter 内容。
- Twitter 可先保持 Embedding `shadow` 模式观察分布，再决定是否切换到 `enforce`。

### Q4：为什么短内容会生成卡片而不是研报？

系统会根据内容字数自动判断输出模式：

- 少于 500 字：生成纯文本卡片，不进行深度分析。
- 不少于 500 字：生成完整 HTML 研报，包括雷达图和深度解析。

### Q5：四层评分为什么仍使用 0–10？

四层内部使用乘积分数，原始范围与报告阈值不一致。系统会保留原始分数用于审计，
同时将各层均为中性的组合映射为 6 分，将当前理论最高组合映射为 10 分。报告和企业
微信只使用正规化后的 0–10 综合分。

### Q6：语义去重为什么显示“跳过”？

语义去重需要当前批次或历史文章作为对比样本。当前主入口尚未加载历史样本，因此会
明确记录为跳过，而不是显示为已经执行。后续接入历史事实源后可启用实际对比。

### Q7：配置 Webhook 后推送失败怎么办？

- 检查 Webhook 地址是否包含真实的 `key`，而非占位符。
- 确认运行环境可以访问 `qyapi.weixin.qq.com`。
- 查看控制台输出的详细错误信息，系统不会再静默忽略推送错误。

### Q8：为什么 X Cookie 不能提交到 GitHub？

`auth_token` 和 `ct0` 可以代表已登录的 X 会话，泄露后可能被他人直接使用。项目只同步
采集代码、测试和配置模板；每台实际运行任务的电脑单独创建 `.local/x/twscrape.db`。

### Q9：twscrape 搜索失败怎么办？

- 先运行专用烟雾测试，不要直接启动完整推送流程。
- 确认复制的是 `auth_token` 和 `ct0` 的 Value，而不是 Cookie 名称或整行文本。
- Cookie 失效时，手动移走旧数据库，再重新运行会话创建脚本。
- 如果出现 X 验证、限流或非公开接口变化，应停止重试并重新评估依赖版本。
- 不要使用个人主账号进行高频测试。

### Q10：Reddit RSS 采集失败怎么办？

- 先用 `scripts/smoke_test_reddit_rss.py` 测试一个明确社区；
- 首次测试只配置一个社区，并确认关键词能命中该社区近期帖子；
- 遇到 429 时停止手动连试，按错误中的建议时间等待；
- RSS 不包含分数、点赞比例、评论数或 flair，不能通过调整解析器补出这些字段；
- 不要通过登录 Cookie、代理池或 IP 轮换规避访问限制。

## 更新日志

### v1.0.0（2026-07-22）

- 发布初始版本。
- 支持 MediaCrawler 与 lingzao-skill 集成。
- 实现动态评分、来源识别和多模式输出。
- 将评分卡调整至报告顶部。
- 支持企业微信 Markdown V2 推送，并增加配置校验。
- 增加 RadIter 决策日志。
- 修复短内容 `.txt` 报告链接返回 404 的问题。
- 修复来源识别中“当前来源”和“原始来源”的区分问题。
- 修复配置占位值校验问题。

## 许可证

本项目采用 [MIT License](LICENSE)。

本项目通过 Git 子模块依赖
[MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)。
MediaCrawler 使用独立的
[Non-Commercial Learning License 1.1](https://github.com/NanmiCoder/MediaCrawler/blob/main/LICENSE)，
仅限非商业学习和研究用途，不受本项目 MIT License 覆盖。

使用者必须同时遵守 MediaCrawler 的许可证、免责声明、目标平台服务条款以及适用的法律法规。

## 致谢

- [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)：社交媒体爬虫。
- [twscrape](https://github.com/vladkens/twscrape)：X 非公开 GraphQL 接口的 Python 封装。
- [Reddit](https://www.reddit.com/)：Atom/RSS 内容来源。
- lingzao-skill：灵造分析能力参考。
- [OpenAI](https://openai.com/)：提供 LLM 能力支持。
