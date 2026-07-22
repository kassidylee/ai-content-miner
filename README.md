# AI Content Miner

> 从海量社交媒体信息中自动完成抓取、智能筛选、研报生成与企业微信推送的知识工作流。

## 项目定位

本项目解决的核心问题是：在信息过载的环境中，如何从大量低质量社交媒体内容中自动筛选高价值信息，并生成结构化研报。

### 适用场景

- AI Agent、量化投资、科技前沿等领域的每日信息聚合
- 研究团队自动生成行业简报
- 个人知识工作流自动化

## 功能列表

| 功能 | 说明 |
| --- | --- |
| 数据爬取 | 小红书、知乎使用 MediaCrawler；X 可选用 Twikit 进行关键词搜索。 |
| 智能分析 | 集成 lingzao-skill 风格的内容诊断，包括账号诊断、爆款内容拆解和对标筛选。 |
| 规则过滤 | 通过字数、关键词和链接检测，快速过滤低质量内容。 |
| 博主白名单 | 为优质来源增加权重，优先处理可信账号发布的内容。 |
| 动态评分 | 根据内容长度自适应选择评分维度：短内容使用四维评分，长内容使用五维评分。 |
| 来源识别 | 自动识别 arXiv ID、GitHub 仓库和转载声明，并标记疑似二手信息。 |
| 多模式输出 | 短内容生成文本卡片（`.txt`）；中长内容生成完整 HTML 研报（`.html`）。 |
| 评分卡前置 | 将评分雷达图和评分表固定展示在报告顶部。 |
| 企业微信推送 | 使用 Markdown V2 格式推送消息，并附带在线阅读链接。 |
| RadIter 日志 | 记录每次决策过程，为后续持续优化提供依据。 |

## 快速开始

### 前置条件

- Python 3.9 或更高版本；使用 X/Twikit 时需要 Python 3.10 或更高版本
- [uv](https://docs.astral.sh/uv/)（用于安装并运行 MediaCrawler）
- OpenAI API Key，或兼容接口的 API Key
- 企业微信机器人 Webhook
- 使用 X 数据源时，需要一个专用 X 账号及仅保存在运行机器上的登录 Cookie

### 1. 克隆项目

```bash
git clone https://github.com/kassidylee/ai-content-miner.git
cd ai-content-miner
```

### 2. 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

本项目与 MediaCrawler 使用相互独立的 Python 环境。本项目的
`requirements.txt` 安装内容处理、推送和可选的 Twikit 依赖；MediaCrawler 依赖由其
`uv.lock` 管理，避免把两个项目的 Playwright、pandas 等版本混装。
Twikit 属于本项目依赖，当前固定为 `2.3.3`，避免其内部接口变化导致不同机器
安装出不一致的行为。该版本的包元数据虽然声明支持 Python 3.8+，但其运行时代码
在 Python 3.9 无法导入，因此本项目会在 X 启动检查中明确要求 Python 3.10+。

### 3. 配置项目

编辑仓库中的 `config.py`：

以下三项为必填配置：

```python
# 1. LLM API Key
API_KEY = "sk-xxxxx"

# 2. 企业微信 Webhook
WECOM_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx"

# 3. 报告预览地址，必须可被企业员工访问
# 开发环境：http://127.0.0.1:8000/reports（仅本机可访问）
# 生产环境：请填写企业内部可访问的实际地址
REPORT_BASE_URL = "http://127.0.0.1:8000/reports"
```

其他配置项请参阅 `config.py` 中的注释。

### 4. 配置 MediaCrawler

当前桥接器明确对齐 MediaCrawler commit
`c9a111be73586bdf6fc44536f088e4db6ed86d64`。在项目根目录克隆并安装：

```bash
git clone https://github.com/NanmiCoder/MediaCrawler.git
cd MediaCrawler
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

### 可选：配置 X 关键词采集

X 不经过 MediaCrawler。将 `config.py` 中的平台设为：

```python
CRAWL_PLATFORM = "x"
SEARCH_KEYWORDS = ["AI Agent", "LLM"]
CRAWL_LIMIT = 20
```

首次使用时，在最终运行任务的电脑上交互式创建本地会话：

```bash
python3 scripts/setup_twikit_session.py
```

脚本通过隐藏输入读取密码，登录成功后只保存 Cookie 到
`.local/x/cookies.json`。密码不会写入文件；`.local/` 已被 Git 忽略。不要将 Cookie、
密码、浏览器登录目录或 `.env` 提交到 GitHub。另一台电脑拉取代码后，需要使用该
电脑自己的专用账号重新创建会话。

相关配置：

```python
TWIKIT_SEARCH_PRODUCT = "Latest"
TWIKIT_RESULTS_PER_QUERY = 20
TWIKIT_MAX_PAGES_PER_QUERY = 5
TWIKIT_TIMEOUT_SECONDS = 120
TWIKIT_LOOKBACK_HOURS = 168
```

Twikit 使用 X 网页端内部接口，不产生官方 X API 调用费，但并非 X 官方服务。Cookie
可能失效，接口可能因 X 改版而中断，账号也可能触发验证或限制。建议只使用可承受风险
的专用账号，并保持低频、只读采集。

### 6. 运行完整工作流

```bash
python3 main.py --check-config
python3 main.py
```

`--check-config` 只检查必填配置和当前选中采集器。小红书、知乎会检查 MediaCrawler
路径、commit 和运行解释器；X 会检查 Twikit 版本、本地 Cookie 和状态文件，
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
│   ├── filter.py               # 规则过滤与博主白名单
│   ├── scorer.py               # 动态评分
│   ├── ral.py                  # 来源识别：arXiv、GitHub、转载检测
│   └── lingzao_adapter.py      # lingzao-skill 风格分析
│
├── crawler/                    # 爬虫模块
│   ├── __init__.py
│   ├── base.py                 # 采集器公共结果与接口
│   ├── factory.py              # 按平台选择采集器
│   ├── mediacrawler_bridge.py  # MediaCrawler 调度
│   └── twikit_bridge.py        # X 关键词搜索与本地去重
├── scripts/
│   └── setup_twikit_session.py # 交互式创建本地 Twikit Cookie
│
├── output/                     # 输出模块
│   ├── __init__.py
│   └── generator.py            # 文本卡片和 HTML 研报生成
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
MediaCrawler（小红书、知乎）或 Twikit（X）
  -> 本次运行内容文件加载与标准化
  -> lingzao 分析
  -> 规则过滤
  -> 动态评分
  -> RAL 溯源
  -> 输出生成
  -> 企业微信推送
```

每次 MediaCrawler 调用都通过 CLI 传入平台、关键词、数量限制、JSONL 格式和
独立输出目录，不会修改 MediaCrawler 的 `config/base_config.py`。当前下游不消费
评论数据，因此调用时明确关闭评论抓取。加载器只读取本次运行产生的
`<type>_contents_<date>.jsonl`，不会递归读取历史输出，也不会把 comments/creators
误当成文章。

Twikit 同样为每次运行创建独立输出目录。它按关键词调用 `Latest` 搜索，单次最多读取
20 条，并在需要时通过 `Result.next()` 翻页；跨关键词按帖子 ID 去重后，按发布时间
排序，只保留默认最近 168 小时的数据，再应用 `CRAWL_LIMIT`。已处理 ID 保存在本机
`data/state/`，且只在报告生成和推送流程成功后确认；失败的数据可在后续运行中再次
处理。

## 输出模式

系统会根据内容字数自动选择输出格式：

| 内容字数 | 输出格式 | 说明 |
| --- | --- | --- |
| 少于 500 字 | 纯文本卡片（`.txt`） | 提取核心观点，不进行深度分析。 |
| 不少于 500 字 | 完整 HTML 研报（`.html`） | 包含评分卡、雷达图和深度精读。 |

中等长度内容（500 至 1500 字）和长内容（超过 1500 字）目前均生成完整 HTML 研报。

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

### `config.py` 关键配置项

| 配置项 | 说明 | 示例 |
| --- | --- | --- |
| `API_KEY` | LLM API Key | `sk-xxxxx` |
| `MODEL_NAME` | 模型名称 | `gpt-4`、`deepseek-chat` |
| `SCORE_THRESHOLD` | 评分阈值，达到该分数的内容才会推送 | `6` |
| `WECOM_WEBHOOK` | 企业微信 Webhook 地址 | `https://qyapi.weixin.qq.com/...` |
| `REPORT_BASE_URL` | 报告预览服务地址，必须可被员工访问 | `http://127.0.0.1:8000/reports` |
| `CRAWL_PLATFORM` | 爬取平台 | `xhs`、`zhihu`、`x` |
| `SEARCH_KEYWORDS` | 搜索关键词 | `["AI Agent", "大模型"]` |
| `MEDIACRAWLER_PATH` | MediaCrawler 仓库路径 | `./MediaCrawler` |
| `MEDIACRAWLER_COMMIT` | 已对齐并校验的 commit | `c9a111b...` |
| `MEDIACRAWLER_PYTHON` | 未使用 uv 时的 Python >=3.11 解释器，可留空 | `/path/to/python` |
| `BLOGGER_WHITELIST` | 博主白名单及权重 | `{"博主A": {"weight": 1.3}}` |
| `ENABLE_RETRIEVAL` | 是否启用来源识别 | `True`、`False` |
| `TWIKIT_COOKIE_FILE` | X 本地 Cookie 路径，不得提交 | `.local/x/cookies.json` |
| `TWIKIT_RESULTS_PER_QUERY` | 每个 X 关键词最多读取条数 | `20` |
| `TWIKIT_MAX_PAGES_PER_QUERY` | 每个 X 关键词最多翻页数 | `5` |
| `TWIKIT_LOOKBACK_HOURS` | X 帖子的本地时间窗口 | `168` |

## 当前接入边界

- 主流程按平台实际调用 MediaCrawler 或 Twikit，然后执行当次内容加载、可选 lingzao
  分析、规则过滤、AI 评分、可选 RAL 来源识别、报告生成和企业微信推送。
- `ENABLE_LINGZAO_ANALYSIS=False` 或 `ENABLE_RETRIEVAL=False` 时会明确跳过对应步骤，
  不做无效果调用。
- 原有 lingzao 适配器中两个始终返回空对象、且没有调用方的方法已移除。
- RAL 当前只做已有文本与 URL 的来源识别；原文抓取、缓存和循环重评仍未实现。
- `find_original_article`、`extract_summary`、`extract_keywords`、`count_words` 和
  `get_recent_decisions` 是已有且有实际实现的工具 API，但当前主流程没有消费者；
  本轮没有为了凑流程而调用它们。手动 `articles/` 加载也不会在自动爬取流程中回退触发。
- MediaCrawler 的 `detail`、`creator` 参数尚未在本项目配置中接入，启动检查会明确
  拒绝这两种模式；当前只支持 `search`。
- 登录方式当前只接入 `qrcode`、`phone`；为避免凭证出现在命令日志或仓库配置中，
  本轮没有接入 cookie 参数。
- X 仅接入 Twikit `2.3.3` 的关键词读取，不包含发帖、点赞、关注、私信、账号池、
  CAPTCHA 绕过或代理轮换。
- X 短帖仍使用项目现有字数过滤和评分规则；本次接入没有调整筛选与评分体系。
- Twikit 依赖非公开接口，无法保证长期稳定。出现登录验证或账号限制时会返回非零退出
  状态，不会把失败显示为采集成功。

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
- 提高过滤阈值，减少进入评分环节的文章数量。
- 仅为评分不低于 6 分的文章生成完整研报。

### Q4：为什么短内容会生成卡片而不是研报？

系统会根据内容字数自动判断输出模式：

- 少于 500 字：生成纯文本卡片，不进行深度分析。
- 不少于 500 字：生成完整 HTML 研报，包括雷达图和深度解析。

### Q5：为什么不同内容的评分维度不同？

系统会根据内容类型动态选择评分维度：

- 短内容或社交媒体短帖：洞察深度、时效性、启发性、可追溯性。
- 长内容、技术博客或论文：相关性、创新性、可复现性、声誉、社区热度。

### Q6：来源识别能做什么，不能做什么？

当前版本支持：

- 识别 arXiv ID，例如 `arxiv.org/abs/2301.12345`。
- 识别 GitHub 仓库，例如 `github.com/user/repo`。
- 检测转载声明，例如“转载”“本文来自”等关键词。
- 标记当前来源平台，例如知乎专栏、微信公众号。

当前版本暂不支持：

- 自动抓取原始页面内容。
- 缓存管理。
- 循环重评。

### Q7：配置 Webhook 后推送失败怎么办？

- 检查 Webhook 地址是否包含真实的 `key`，而非占位符。
- 确认运行环境可以访问 `qyapi.weixin.qq.com`。
- 查看控制台输出的详细错误信息，系统不会再静默忽略推送错误。

### Q8：Twikit 为什么不能把 Cookie 提交到 GitHub？

Cookie 可以代表已登录的 X 会话，泄露后可能被他人直接使用。项目只同步采集代码、
测试和配置模板；每台实际运行任务的电脑单独创建 Cookie。Cookie 和本地已处理状态均
在 Git 忽略目录内。

### Q9：Twikit 搜索失败怎么办？

- 先运行 `python3 main.py --check-config`，检查依赖版本和 Cookie 文件。
- Cookie 失效时，先将旧文件安全移走，再运行 `python3 scripts/setup_twikit_session.py`。
- 如果 X 内部接口已经变化，应升级或修复 Twikit 适配后再运行，不要忽略错误继续推送。
- 不要使用个人主账号进行高频测试。

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

## 致谢

- [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)：社交媒体爬虫。
- [Twikit](https://github.com/d60/twikit)：X 内部接口的非官方 Python 封装。
- lingzao-skill：灵造分析能力参考。
- [OpenAI](https://openai.com/)：提供 LLM 能力支持。
