# AI Content Miner

AI Content Miner 将多个内容平台的帖子统一为结构化信息，经过分层筛选后生成每个平台
一个聚合 HTML 页面。页面中的主链接始终指向原帖，不再生成逐条深度分析研报。

当前以 X / Twitter 作为第一阶段完整实现的平台。小红书和知乎继续保留现有
MediaCrawler 采集桥接器，并复用相同的标准化、筛选、摘要、存储和页面模块；
不支持评论能力的平台会跳过第三层，不会导致主流程失败。

## 处理流程

```text
平台采集器
  -> 统一内容结构
  -> 第一层：配置化规则筛选
  -> 第二层：多主题 Embedding 相似度筛选
  -> 第三层：可选评论区质量筛选
  -> 极简标题、摘要和分层标签
  -> data/processed/<platform>.jsonl
  -> reports/<platform>.html
  -> 确认本次已处理 ID
  -> 可选企业微信通知
```

处理模块只读取统一字段，不依赖 twscrape 或 MediaCrawler 的原始对象。后续增加平台时，
主要工作是新增采集与字段转换；通用筛选和输出模块不需要增加平台分支。

## 结构化字段

每条内容至少包含：

| 字段 | 说明 |
| --- | --- |
| `id` | `<platform>:<platform_item_id>` 形式的统一 ID |
| `platform_item_id` | 平台原始内容 ID |
| `platform` | 稳定平台键，例如 `x`、`xhs`、`zhihu` |
| `title` | 原平台标题；没有标题时生成极简标题 |
| `content` | 原始正文 |
| `abstract` | 一到两句话的事实性摘要 |
| `tags` | 带 `level`、`parent_id` 和来源的分层标签 |
| `entities` | 原文或链接中明确出现的项目、论文、模型或产品 |
| `source_url` | 原帖链接 |
| `referenced_urls` | 展开的论文、代码仓库或其他外部链接 |
| `published_at` | 原始发布时间 |
| `metrics` | 点赞、回复、转发、收藏、引用和浏览数据 |
| `filter_metadata` | 每层决定、分数、命中规则和最终原因 |
| `processed_at` | 本次完成处理的时间 |

结构化结果不会保存完整 Embedding 向量、Cookie、API Key、完整评论正文集合或不必要的
采集器原始响应。

## 三层筛选

### 第一层：规则筛选

`PLATFORM_FILTERS` 包含通用默认值和平台覆盖项。当前 X 配置会检查：

- 平台 ID、正文、原帖 URL 和发布时间；
- 语言；
- 有意义文本长度；
- 回复、转推、引用和敏感内容类型；
- 排除关键词；
- 本批次内相同正文和相同外链。

这一层不调用外部模型，删除项不会进入后续 Embedding、评论和摘要调用。

### 第二层：Embedding 筛选

`INTEREST_TOPICS` 为每个兴趣主题分别配置：

- 稳定主题 ID；
- 标签和主题描述；
- 独立相似度阈值；
- 对应受控标签 ID。

系统批量生成主题和内容向量，计算每条内容与所有主题的余弦相似度。任一主题达到自己的
阈值即通过。完整分数、最高相似主题和达标主题会写入 `filter_metadata`，但向量本身
不会落盘。

`EMBEDDING_FILTER_MODE` 支持：

- `shadow`：低分项继续处理，但记录 `shadow_drop`，用于校准阈值；
- `enforce`：所有主题均未达标时正式删除。

建议先使用默认 `shadow` 收集样本，人工检查后再切换为 `enforce`。

### 第三层：评论区筛选

评论能力是可选接口。X 桥接器通过 twscrape 获取有限数量的直接回复，并转换为通用评论
结构。筛选器综合考虑：

- 有效回复数量；
- 明确质疑内容真实性或正确性的关键词；
- 不同质疑作者数量；
- 质疑回复比例；
- 按点赞数截断加权后的质疑比例。

回复为空、样本不足或接口不可用时只记录低置信度或跳过原因。只有足量、不同作者且高权重
的明确质疑达到配置阈值时才删除。原作者补充、重复回复、同一账号连续回复和明显机器人
账号不会放大质疑信号。

## 极简摘要和标签

模型对每条最终保留内容只调用一次，同时返回标题、摘要、受控标签 ID 和实体。系统会：

- 保留平台原生标题；
- 对无标题内容生成不超过配置长度的极简标题；
- 将摘要限制为一到两句话；
- 拒绝 `TAG_TAXONOMY` 中不存在的一级或二级标签；
- 自动补充 Embedding 达标主题对应的标签；
- 用规则生成短消息、长消息、论文和项目发布等内容形式标签；
- 只接受能在原文或链接文字中找到的动态三级实体。

摘要模型失败不会删除内容，系统会使用正文首句、Embedding 主题和内容形式规则生成退化
结果。

## 快速开始

### 环境要求

- Python 3.10 或更高版本；
- OpenAI API 或兼容的 Chat Completions、Embeddings 接口；
- X 使用 `twscrape==0.19.2`，需要本机浏览器登录会话；
- 小红书和知乎使用 MediaCrawler 时，需要 `uv` 和独立的 Python 3.11 环境。

安装项目依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

### 基础配置

编辑 `config.py`：

```python
API_KEY = "your-real-api-key"
BASE_URL = "https://api.openai.com/v1"
MODEL_NAME = "your-chat-model"

CRAWL_PLATFORM = "x"
SEARCH_KEYWORDS = ["AI Agent", "推理模型", "多模态"]

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_FILTER_MODE = "shadow"
```

根据实际兴趣修改 `INTEREST_TOPICS`，并逐个校准 `threshold`。标签 ID 应存在于
`TAG_TAXONOMY`。

企业微信默认关闭。需要时配置：

```python
ENABLE_WECOM = True
WECOM_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
REPORT_BASE_URL = "https://your-host.example/reports"
```

通知中的每条主链接直接指向 `source_url`。通知失败发生在结果落盘、页面生成和状态确认
之后，不会导致同一批内容在下次运行时被重复处理。

## 配置 X 会话

X 不经过 MediaCrawler。先在浏览器中正常登录 X，再从浏览器开发者工具的
`Storage -> Cookies -> https://x.com` 中读取 `auth_token` 和 `ct0` 的值。
不要把 Cookie 发到聊天、截图或 GitHub。

运行本机会话脚本：

```bash
.venv/bin/python scripts/setup_twscrape_session.py
```

脚本将 Cookie 写入 Git 已忽略的 `.local/x/twscrape.db`，并设置为仅当前用户可读写。
不同电脑需要分别创建会话数据库。

先执行小规模只读烟雾测试：

```bash
.venv/bin/python scripts/smoke_test_twscrape.py "AI Agent" --limit 3
```

烟雾测试只验证搜索和原始 JSONL 写入，不调用 Embedding、摘要、评论筛选、结构化存储或
通知，也不会确认 seen IDs。

twscrape 使用 X 的非公开 GraphQL 接口，可能因接口变化、Cookie 失效、限流或账号验证
而中断。任何采集失败都会返回非零退出状态。

## 配置 MediaCrawler

当前桥接器对齐 MediaCrawler commit：

```text
c9a111be73586bdf6fc44536f088e4db6ed86d64
```

安装示例：

```bash
git clone https://github.com/NanmiCoder/MediaCrawler.git
cd MediaCrawler
git checkout c9a111be73586bdf6fc44536f088e4db6ed86d64
uv sync
cd ..
```

MediaCrawler 使用自己的依赖环境。当前桥接器只接入 `search`，并明确关闭评论和子评论
抓取；因此小红书和知乎会在第三层记录评论能力未启用。

## 运行

先检查当前平台所需的依赖、配置和本地会话：

```bash
.venv/bin/python main.py --check-config
```

执行完整工作流：

```bash
.venv/bin/python main.py
```

关键失败语义：

| 情况 | 行为 |
| --- | --- |
| 配置或采集失败 | 非零退出，不开始后续处理 |
| 本次没有新内容 | 非零无数据状态 |
| Embedding 失败 | 非零退出，不写结果，不确认 seen IDs |
| 评论接口失败 | 单条记录 `REPLIES_UNAVAILABLE`，继续处理 |
| 摘要模型失败 | 使用本地退化结果，继续处理 |
| 结构化结果或 HTML 写入失败 | 非零退出，不确认 seen IDs |
| 企业微信失败 | 非零通知状态，但已落盘并已确认 seen IDs |

## 输出

原始采集数据：

```text
data/crawler_runs/<run_id>/<platform>/jsonl/
```

包含保留项和删除项的结构化事实源：

```text
data/processed/<platform>.jsonl
```

每个平台一个聚合页面：

```text
reports/<platform>.html
```

页面只展示保留期内最新的 `final_decision=keep` 记录，按统一 ID 去重并按发布时间倒序。
标题、摘要、标签和链接均经过转义或协议校验，外部链接使用安全的新窗口属性。

可以启动本地静态服务：

```bash
.venv/bin/python server.py
```

然后访问：

```text
http://127.0.0.1:8000/reports/x.html
```

## 项目结构

```text
ai-content-miner/
├── analyzer/
│   ├── filter.py              # 第一层规则筛选
│   ├── embedding_filter.py    # 第二层多主题语义筛选
│   ├── comment_filter.py      # 第三层可选评论区筛选
│   ├── enricher.py            # 极简摘要和分层标签
│   └── pipeline.py            # 通用筛选编排
├── crawler/
│   ├── base.py                # 采集与可选评论能力边界
│   ├── factory.py             # 平台采集器选择
│   ├── mediacrawler_bridge.py # 小红书、知乎采集适配
│   └── twscrape_bridge.py     # X 搜索与回复适配
├── notifier/
│   └── wecom.py               # 可选企业微信通知
├── output/
│   └── feed_renderer.py       # 确定性平台聚合页
├── utils/
│   ├── parser.py              # 平台数据标准化
│   └── result_store.py        # 结构化事实源读写
├── scripts/
│   ├── setup_twscrape_session.py
│   └── smoke_test_twscrape.py
├── tests/
├── config.py
├── main.py
└── server.py
```

## 测试

全部外部模型、评论和网络调用在单元测试中使用替身：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

测试覆盖平台标准化、三层筛选、逐主题阈值、回复失败隔离、摘要退化、标签校验、结构化
存储、HTML 安全、状态确认时机和可选通知。

更详细的设计与阶段计划见
[`docs/twitter-structured-feed-refactor-plan.md`](docs/twitter-structured-feed-refactor-plan.md)。
