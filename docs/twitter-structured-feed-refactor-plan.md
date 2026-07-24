# Twitter/X 结构化信息流重构方案

## 1. 文档信息

- 目标平台：Twitter/X
- 当前代码基线：`codex/reddit-praw-collector`
- 当前提交：`50a7fd6d420527091318c7f1a5ac5f656de8ce94`
- 文档状态：设计方案，尚未实施
- 一期目标：完成 Twitter/X 单平台 MVP，不同时改造其他平台

## 2. 结论摘要

当前项目的核心链路是“抓取内容后进行深度分析、AI 多维评分、逐条生成 TXT/HTML 研报，再推送企业微信”。新目标应调整为：

1. 在配置范围内采集 Twitter/X 推文；
2. 将每条推文转换为统一的结构化记录；
3. 依次执行规则筛选、Embedding 语义筛选和回复区筛选；
4. 只为最终保留的推文生成极简标题、摘要和分层标签；
5. 保存每条推文经过各层筛选时的分数、规则命中和最终原因；
6. 每个平台只生成一个聚合 HTML，Twitter/X 对应 `reports/x.html`；
7. 用户点击内容时直接进入原始推文或推文引用的论文、项目和文章，不再进入逐条生成的二次研报。

一期选择 Twitter/X 的原因是：

- 当前仓库已经完成 `twscrape==0.19.2` 的关键词搜索、字段转换、时间窗口、去重、本地状态和测试；
- 已经存在本地 Cookie 会话创建脚本和真实只读烟雾测试记录；
- `twscrape==0.19.2` 提供 `API.tweet_replies(tweet_id, limit=...)`，可以实现基础版第三层回复筛选；
- 不需要先建设作者或机构白名单。

需要同时接受以下现实约束：

- Twscrape 使用 X 的非公开 GraphQL 接口，可能因接口改版、Cookie 失效、限流或账号验证而中断；
- “整合平台所有推文”在一期中应定义为“整合配置的关键词、时间窗口和数量限制内采集到的全部唯一候选推文”，而不是抓取整个 Twitter/X；
- 回复区筛选属于可跳过的增强能力，不能因为回复接口暂时不可用而使整个主流程必然失败。

## 3. 当前代码现状

### 3.1 当前主流程

当前 [`main.py`](../main.py) 的实际处理顺序是：

```text
采集器配置检查
→ 平台采集
→ 本次 JSONL 数据加载
→ Lingzao 深度分析
→ 规则过滤
→ LLM 多维评分
→ 可选 RAL 来源识别
→ 逐条生成 TXT/HTML
→ 企业微信推送
→ acknowledge 已处理 ID
```

主要问题包括：

- [`analyzer/filter.py`](../analyzer/filter.py) 只有长度、少量中文低质量关键词和正文链接检查，不适合 Twitter 短消息；
- [`analyzer/lingzao_adapter.py`](../analyzer/lingzao_adapter.py) 面向小红书式账号诊断和爆款分析，与新目标无关；
- [`analyzer/scorer.py`](../analyzer/scorer.py) 仍在做深度、创新性、声誉等主观评分，并硬编码 AI Agent 相关性；
- [`analyzer/ral.py`](../analyzer/ral.py) 服务于逐篇研报的来源识别，不应继续作为主处理阶段；
- [`output/generator.py`](../output/generator.py) 会为每条内容生成 TXT 或完整 HTML 研报；
- [`notifier/wecom.py`](../notifier/wecom.py) 当前链接到系统生成的报告，而不是原始内容；
- [`utils/raditer.py`](../utils/raditer.py) 只记录最终生成的内容，没有记录被各层删除的候选项；
- 当前 Twitter 采集只保存第一次命中的 `search_keyword`，同一推文匹配多个关键词时没有汇总命中上下文。

### 3.2 当前可复用能力

以下代码可以继续复用：

- [`crawler/base.py`](../crawler/base.py) 中的采集运行结果和最小采集器协议；
- [`crawler/factory.py`](../crawler/factory.py) 中的平台选择逻辑；
- [`crawler/twscrape_bridge.py`](../crawler/twscrape_bridge.py) 中的依赖检查、Cookie 会话检查、关键词搜索、时间窗口、本次运行目录、去重和 seen IDs；
- [`utils/parser.py`](../utils/parser.py) 中的显式文件加载入口和基础字段标准化；
- [`server.py`](../server.py) 中的静态文件服务；
- 现有 Twitter、Parser、主流程和采集器测试。

## 4. 一期范围与设计原则

### 4.1 一期必须完成

- Twitter/X 现有采集流程接入新数据结构；
- 第一层规则筛选；
- 第二层多主题 Embedding 筛选；
- 基础版回复区筛选；
- 极简标题和摘要；
- 配置化分层标签；
- 原始推文和外部引用链接；
- 所有候选项的筛选元数据；
- `data/processed/x.jsonl` 结构化结果；
- 单一聚合页面 `reports/x.html`；
- 主流程、状态确认和错误码调整；
- 测试和 README 更新；
- 停止旧深度分析、主观评分和逐条研报流程。

### 4.2 一期明确不做

- 多平台同时运行；
- Reddit、小红书或知乎的新流程适配；
- 作者、机构或账号白名单；
- 账号池自动扩容；
- Cookie 自动更新；
- CAPTCHA 绕过；
- 代理轮换；
- 完整 thread 抓取和拼接；
- 转推关系图；
- 数据库、Redis、消息队列或异步任务系统；
- 通用插件注册表或复杂抽象基类；
- 单独的评论情感模型；
- 每条推文单独生成 HTML；
- LLM 深度分析、观点评价、风险扩写和研报生成。

### 4.3 简化原则

当前项目使用可变 `dict` 在采集、解析和分析模块间传递数据。为了避免一期同时引入第二套模型，建议先继续使用统一字典结构，通过：

- 明确字段规范；
- 集中的标准化函数；
- 类型注释；
- 单元测试；
- 稳定 reason code；

保证数据边界。后续若多平台适配增多，再考虑迁移为 dataclass 或其他强类型模型。

## 5. 目标流程

```text
Twscrape 关键词搜索
→ 本次运行原始 JSONL
→ Twitter 数据标准化
→ 第一层规则筛选
→ 第二层 Embedding 批量筛选
→ 对第二层通过项按需抓取回复
→ 第三层回复区筛选
→ 对最终保留项生成标题、摘要和标签
→ 保存所有候选项及 filter_metadata
→ 重建 reports/x.html
→ acknowledge 本次唯一 tweet IDs
→ 可选企业微信通知
```

成本控制顺序必须保持：

- 第一层未通过：不调用 Embedding、不抓回复、不生成摘要；
- 第二层 enforce 模式未通过：不抓回复、不生成摘要；
- 第三层未通过：不生成摘要；
- 只有最终保留项才调用摘要和标签模型；
- HTML 使用本地模板生成，不调用模型。

## 6. 统一推文结构

建议标准化记录如下：

```json
{
  "id": "x:2079834669860966881",
  "platform_item_id": "2079834669860966881",
  "platform": "x",
  "title": "AI Agent 支付中的结算速度问题",
  "content": "推文原始正文",
  "quoted_content": "",
  "abstract": "讨论两个 AI Agent 交易时如何平衡结算速度和安全性。",
  "tags": [
    {
      "ids": ["ai", "ai-agent"],
      "labels": ["AI", "AI Agent"],
      "source": "model"
    },
    {
      "ids": ["content-form", "short-message"],
      "labels": ["内容形式", "短消息"],
      "source": "rule"
    }
  ],
  "source_url": "https://x.com/user/status/2079834669860966881",
  "referenced_urls": [
    {
      "url": "https://github.com/example/project",
      "label": "github.com/example/project",
      "domain": "github.com"
    }
  ],
  "published_at": "2026-07-22T07:43:21+00:00",
  "author": {
    "username": "user",
    "display_name": "User"
  },
  "metrics": {
    "like_count": 12,
    "reply_count": 5,
    "retweet_count": 3,
    "quote_count": 1,
    "bookmark_count": 2,
    "view_count": 2000
  },
  "platform_metadata": {
    "lang": "en",
    "hashtags": ["AI", "Agent"],
    "is_reply": false,
    "is_retweet": false,
    "is_quote": false,
    "possibly_sensitive": false,
    "conversation_id": "2079834669860966881",
    "matched_keywords": ["AI Agent"]
  },
  "filter_metadata": {
    "stages": [],
    "final_decision": "keep",
    "final_reason_codes": ["ALL_STAGES_PASSED"]
  },
  "processed_at": "2026-07-24T10:00:00+08:00"
}
```

### 6.1 URL 规则

- `source_url` 始终保存原始推文 URL；
- `referenced_urls` 保存 Twscrape `Tweet.links` 中展开后的链接；
- 不直接使用正文中的 `t.co` 短链接作为最终外链；
- HTML 主入口为“查看原帖”；
- GitHub、arXiv、项目官网或文章链接作为次要入口；
- 所有 URL 写入前需要验证为 `http` 或 `https`；
- 不生成指向逐条本地 HTML 的链接。

### 6.2 标题规则

Twitter 推文通常没有原始标题，因此：

- 采集和筛选阶段不依赖模型标题；
- 可以暂时使用清洗后正文前 80 个字符作为内部显示标题；
- 三层筛选通过后，由摘要模块生成 15～30 字的极简标题；
- 模型失败时，退化为清洗后正文前 40 个字符；
- 标题只描述主题，不加入“重磅”“深度”“必看”等评价词。

## 7. Twitter 采集与标准化调整

### 7.1 需要从 Twscrape 补充的字段

当前采集器已经保存正文、用户、时间、语言和互动量。建议补充：

- `conversationIdStr`；
- `inReplyToTweetIdStr`；
- `retweetedTweet` 是否存在；
- `quotedTweet` 是否存在及其正文；
- `possibly_sensitive`；
- `hashtags`；
- `links` 中的展开 URL、显示文本和短链接；
- 引用推文 URL；
- 同一推文匹配到的所有搜索关键词。

### 7.2 去重策略

采集阶段保留：

- seen IDs 去重；
- 本次运行内 tweet ID 去重。

但同一推文因多个关键词重复出现时，不应简单丢弃后续搜索上下文。应按 tweet ID 合并：

```json
{
  "matched_keywords": ["AI Agent", "LLM", "multi-agent"]
}
```

第一层规则可以进一步检查：

- 规范化正文重复；
- 相同外链重复；
- 明显重复推广内容。

同一 tweet ID 的多次命中属于采集归并，不需要在审计数据中生成多条“重复删除”记录。

## 8. 第一层：规则型筛选

### 8.1 目标

第一层只执行低成本、确定性较高的判断，尽量减少后续 Embedding、回复请求和 LLM 调用。

### 8.2 Twitter 初始规则

建议在 `config.py` 中建立平台级配置，例如：

```python
PLATFORM_FILTERS = {
    "x": {
        "lookback_hours": 168,
        "allowed_languages": ["zh", "en"],
        "allow_replies": False,
        "allow_retweets": False,
        "allow_quotes": True,
        "drop_sensitive": True,
        "min_meaningful_chars": 20,
        "exclude_keywords": [
            "airdrop",
            "giveaway",
            "casino",
            "betting",
            "招聘",
            "返利",
            "空投",
            "博彩",
        ],
    }
}
```

建议规则如下：

1. 缺少 tweet ID、正文、发布时间或有效原帖 URL：删除；
2. 超出时间窗口：删除；
3. `possibly_sensitive=true`：默认删除；
4. 纯转推：默认删除；
5. 回复帖：一期默认删除，可配置开启；
6. 引用推文：允许，并把引用正文加入后续语义输入；
7. 去除 URL、无意义 `@mention`、重复 hashtag 和装饰字符后，正文少于 20 个字符，且没有有效外链或媒体：删除；
8. 命中明确广告、空投、博彩、返利、批量营销词：删除；
9. 语言不在允许范围：删除；
10. 相同规范化正文或相同外链的重复推广内容：删除。

不建议在第一层再次强制要求兴趣关键词出现，因为：

- 采集阶段已经按关键词搜索；
- 关键词匹配可能漏掉语义相关但没有使用同一术语的推文；
- 第二层 Embedding 才是相关性判断的主要依据。

### 8.3 第一层元数据

通过示例：

```json
{
  "stage": "rules",
  "decision": "pass",
  "reason_codes": ["RULES_PASSED"],
  "details": {
    "language": "en",
    "meaningful_chars": 126,
    "is_reply": false,
    "is_retweet": false
  }
}
```

删除示例：

```json
{
  "stage": "rules",
  "decision": "drop",
  "reason_codes": ["RULE_RETWEET_NOT_ALLOWED"],
  "details": {
    "is_retweet": true
  }
}
```

## 9. 第二层：Embedding 语义筛选

### 9.1 目标

系统需要将第一层通过的每条推文与多个预先配置的兴趣主题进行语义比较。

完整顺序：

```text
第一层通过项
→ 构造 Embedding 文本
→ 主题描述批量生成 Embedding
→ 推文分批生成 Embedding
→ 每条推文与所有主题计算余弦相似度
→ 每个主题使用自己的阈值判断
→ 写入 filter_metadata
→ shadow 或 enforce 决策
```

只有第一层规则通过的内容才能调用 Embedding API。

### 9.2 配置

建议增加：

```python
EMBEDDING_MODEL = "由当前 API 服务支持的 embedding 模型名称"
EMBEDDING_BATCH_SIZE = 50
EMBEDDING_MAX_CHARS = 6000

# shadow：计算和记录，不真正删除
# enforce：正式删除所有主题均未达到各自阈值的内容
EMBEDDING_FILTER_MODE = "shadow"

INTEREST_TOPICS = [
    {
        "id": "ai-agent",
        "label": "AI Agent",
        "description": (
            "AI Agent、智能体框架、工具调用、任务规划、"
            "多智能体协作、Agent 工作流和相关开源项目"
        ),
        "threshold": 0.35,
        "tag_id": "ai-agent",
    },
    {
        "id": "reasoning-model",
        "label": "推理模型",
        "description": (
            "大语言模型的复杂推理、思维链、test-time compute、"
            "数学推理、代码推理和推理模型训练"
        ),
        "threshold": 0.35,
        "tag_id": "reasoning-model",
    },
    {
        "id": "multimodal",
        "label": "多模态",
        "description": (
            "视觉语言模型、语音模型、图像生成、视频生成、"
            "多模态理解和跨模态推理"
        ),
        "threshold": 0.35,
        "tag_id": "multimodal",
    },
    {
        "id": "ai-infra",
        "label": "AI Infra",
        "description": (
            "大模型训练和推理基础设施、GPU、分布式训练、"
            "推理加速、模型部署、量化和服务框架"
        ),
        "threshold": 0.35,
        "tag_id": "ai-infra",
    },
]
```

要求：

- 主题、描述和阈值只能来自配置；
- 主题 ID 必须唯一；
- `description` 不能为空；
- `threshold` 必须是合法数值；
- `tag_id` 必须能在标签体系中找到；
- `EMBEDDING_MODEL` 不能为空；
- 初始阈值 `0.35` 仅用于 shadow 数据采集，不应直接视为最终阈值。

### 9.3 Embedding 输入构造

新增独立且可单元测试的函数：

```python
def build_embedding_text(item: dict) -> str:
    ...
```

优先包含：

1. 推文正文；
2. 引用推文正文；
3. 展开后的外链域名或有意义的链接文字；
4. 少量有明确技术含义的 hashtag。

不要加入：

- 点赞数；
- 回复数；
- 转发数；
- 浏览量；
- 发布时间；
- 无意义的 `@username`；
- 大量重复 hashtag；
- 第一层或第三层产生的分数。

处理要求：

- 清理重复空白；
- 去掉纯装饰字符；
- 合并重复 hashtag；
- 保留技术词、模型名和项目名；
- 最大长度为 `EMBEDDING_MAX_CHARS`；
- 不修改原始 `item["content"]`。

示例：

```text
We released an open-source framework that lets LLMs plan tasks and call external tools.

引用内容：A new benchmark for autonomous coding agents.

相关链接：github.com
```

### 9.4 Embedding API 调用

复用现有 OpenAI Python SDK 和兼容接口配置：

```python
client = OpenAI(
    api_key=config.API_KEY,
    base_url=config.BASE_URL,
)
```

批量调用：

```python
response = client.embeddings.create(
    model=config.EMBEDDING_MODEL,
    input=texts,
)
```

要求：

1. 一次运行中，每个兴趣主题描述只生成一次向量；
2. 推文按照 `EMBEDDING_BATCH_SIZE` 分批；
3. 不允许每条推文单独请求；
4. 主题和推文必须使用同一个模型；
5. 根据 `response.data[*].index` 恢复输入顺序；
6. 必须检查返回数量；
7. 不把完整向量写入日志、JSONL 或 `filter_metadata`；
8. 一期只在当前进程中复用主题向量；
9. 一期不加入磁盘缓存、数据库或 Redis。

### 9.5 余弦相似度

使用：

```text
similarity(A, B) = dot(A, B) / (norm(A) * norm(B))
```

使用 Python 标准库 `math` 实现，不增加 NumPy 依赖。

必须处理：

- 空向量；
- 零范数；
- 向量维度不一致；
- 非数字元素；
- API 返回数量不一致。

维度不一致、向量格式错误和返回数量不一致属于流程错误，不能静默忽略。

### 9.6 多主题阈值判断

每条推文必须与所有主题比较，例如：

```json
{
  "ai-agent": 0.63,
  "reasoning-model": 0.28,
  "multimodal": 0.21,
  "ai-infra": 0.34
}
```

实际判定应逐个主题使用自己的阈值：

```text
topic_passed = similarity(topic) >= threshold(topic)
```

最终规则：

- 任一主题达到自己的阈值：通过；
- 所有主题都低于各自阈值：低于阈值；
- `best_topic` 记录最高原始相似度主题，用于展示和默认标签；
- `matched_topics` 记录所有达到自身阈值的主题。

不建议只比较“最高相似主题”的阈值。原因是不同主题阈值可能不同：

```text
主题 A：score=0.44，threshold=0.50
主题 B：score=0.42，threshold=0.35
```

如果只看最高分主题 A，会错误删除这条已经满足主题 B 阈值的推文。

阈值比较使用未四舍五入的原始浮点数；写入元数据时统一保留四位小数。

### 9.7 Shadow 与 Enforce

`shadow`：

- 所有主题均未达标时，记录 `shadow_drop`；
- 推文仍继续进入后续流程；
- 用于观察真实分数分布和人工校准；
- 最终页面可选择继续展示，但应能从审计数据识别它本应被过滤。

`enforce`：

- 所有主题均未达标时，记录 `drop`；
- 不抓取回复；
- 不生成摘要和标签；
- 不进入最终 HTML。

建议先运行 100～200 条真实推文的 shadow 数据，人工标注“相关/不相关”，再按主题分别调整阈值。

### 9.8 Embedding 元数据

通过示例：

```json
{
  "stage": "embedding",
  "decision": "pass",
  "mode": "shadow",
  "topic_scores": {
    "ai-agent": 0.6300,
    "reasoning-model": 0.2800,
    "multimodal": 0.2100,
    "ai-infra": 0.3400
  },
  "matched_topics": ["ai-agent"],
  "best_topic": "ai-agent",
  "best_topic_label": "AI Agent",
  "best_score": 0.6300,
  "best_topic_threshold": 0.3500,
  "reason_codes": ["EMBEDDING_THRESHOLD_PASSED"]
}
```

低于阈值但处于 shadow：

```json
{
  "stage": "embedding",
  "decision": "shadow_drop",
  "mode": "shadow",
  "topic_scores": {
    "ai-agent": 0.2100,
    "reasoning-model": 0.2300,
    "multimodal": 0.1800,
    "ai-infra": 0.2400
  },
  "matched_topics": [],
  "best_topic": "ai-infra",
  "best_topic_label": "AI Infra",
  "best_score": 0.2400,
  "best_topic_threshold": 0.3500,
  "reason_codes": ["EMBEDDING_BELOW_ALL_TOPIC_THRESHOLDS"]
}
```

Enforce 正式删除：

```json
{
  "stage": "embedding",
  "decision": "drop",
  "mode": "enforce",
  "matched_topics": [],
  "best_topic": "ai-infra",
  "best_score": 0.2400,
  "best_topic_threshold": 0.3500,
  "reason_codes": ["EMBEDDING_BELOW_ALL_TOPIC_THRESHOLDS"]
}
```

不保存完整向量。

### 9.9 空输入

如果第一层没有任何通过项：

- 不调用主题或推文 Embedding API；
- 正常返回空结果；
- 主流程继续完成审计和输出；
- 不是系统错误。

如果单条推文构造出的 Embedding 文本为空：

- 不为该条调用 API；
- shadow 模式记录 `shadow_drop`；
- enforce 模式记录 `drop`；
- reason code 为 `EMBEDDING_EMPTY_TEXT`。

### 9.10 失败策略

以下错误必须抛出 `EmbeddingFilterError` 或等价异常：

- Embedding API 请求失败；
- `EMBEDDING_MODEL` 未配置；
- `INTEREST_TOPICS` 无效；
- API 返回数量与输入数量不一致；
- API index 无效或重复；
- 向量格式错误；
- 主题和推文向量维度不一致；
- 余弦相似度无法计算。

主流程处理：

1. 返回独立的非零退出状态；
2. 不进入回复、摘要或 HTML 写入阶段；
3. 不调用采集器 `acknowledge()`；
4. 不把本次 tweet IDs 写入 seen IDs；
5. 错误信息不得包含 API Key、Cookie、完整请求内容或完整向量。

Embedding 是核心筛选层，API 失败时不能默认放行所有内容。

### 9.11 模块边界

建议新增：

```text
analyzer/embedding_filter.py
```

至少包含：

- `EmbeddingFilterError`
- `build_embedding_text`
- `cosine_similarity`
- 配置校验
- 主题向量生成
- 推文批量向量生成
- API index 顺序恢复
- 多主题相似度计算
- per-topic threshold 判断
- shadow/enforce 判断
- Embedding 元数据写入

不创建：

- 抽象 Filter 基类；
- 插件注册表；
- 数据库层；
- 缓存服务；
- 异步任务系统。

## 10. 第三层：回复区筛选

### 10.1 获取方式

在第二层通过后，按需调用：

```python
API.tweet_replies(int(tweet_id), limit=20)
```

Twscrape 会返回直接回复 Tweet，可使用：

- `rawContent`
- `user.username`
- `likeCount`
- `date`
- `inReplyToTweetId`

进行基础筛选。

### 10.2 采样与清洗

- 每条推文最多读取 20 条直接回复；
- 在本地按 `likeCount` 排序；
- 忽略空回复；
- 忽略明显机器人和重复回复；
- 原作者自己的回复视为补充说明，不计入负面比例；
- 按不同用户名统计，避免一个账号连续回复操纵结果；
- 不抓取无限层级回复树。

### 10.3 负面质量信号

配置化关键词可包括：

- `misleading`
- `incorrect`
- `fabricated`
- `fake`
- `clickbait`
- `no evidence`
- `not reproducible`
- `瞎说`
- `胡扯`
- `错误`
- `造假`
- `误导`
- `不可信`
- `标题党`

不要把普通意见分歧、反问或一般负面情绪直接视为内容造假。

### 10.4 初始删除条件

建议使用比 Reddit 更严格的条件，因为 X 回复区噪声和攻击性更高。

主要条件：

- 有效回复不少于 5；
- 至少 3 个不同作者明确质疑真实性或正确性；
- 明确质疑回复占比不低于 40%；
- 按回复点赞数加权后的负面比例不低于 60%。

点赞权重：

```python
weight = max(1, min(like_count, 50))
```

辅助条件：

- 至少 2 条明确质疑来自不同作者；
- 每条至少获得 5 个赞；
- 加权负面比例不低于 50%。

其他情况：

- 回复少于 5 条：保留，记录 `REPLIES_LOW_SAMPLE`；
- 回复为 0：保留，记录 `REPLIES_EMPTY`；
- 回复接口失败：跳过，记录 `REPLIES_UNAVAILABLE`；
- 少量质疑：保留，记录比例和证据；
- 不能仅因回复数量少而删除。

### 10.5 回复接口失败策略

回复区与 Embedding 的失败策略不同：

- Embedding 失败：主流程失败，不 acknowledge；
- 回复接口失败：第三层跳过，主流程可以继续；
- 每条推文分别记录回复抓取状态；
- 不得把回复接口错误伪装为“没有负面回复”。

## 11. 极简摘要和标签

### 11.1 调用时机

只有最终保留项才调用摘要和标签模型。

一次模型调用同时返回：

- `title`
- `abstract`
- 受控标签 ID
- 正文中明确出现的项目、论文或模型实体

不再进行：

- 账号诊断；
- 爆款分析；
- 创新性评分；
- 声誉评分；
- 深度精读；
- 风险扩写；
- 应用场景扩写。

### 11.2 摘要要求

- 1～2 句话；
- 只说明这条推文主要讲什么；
- 不进行评价；
- 不添加原文没有的信息；
- 不使用“本文深入探讨”“值得关注”等套话；
- 短推文优先控制为一句话。

失败退化：

- 标题：清洗后正文前 40 个字符；
- 摘要：清洗后的第一句话；
- 主题标签：使用 Embedding `matched_topics`；
- 内容形式标签：继续使用规则判断。

### 11.3 分层标签

建议配置结构：

```python
TAG_TAXONOMY = [
    {"id": "ai", "label": "AI", "level": 1, "parent_id": None},
    {
        "id": "ai-agent",
        "label": "AI Agent",
        "level": 2,
        "parent_id": "ai",
    },
    {
        "id": "reasoning-model",
        "label": "推理模型",
        "level": 2,
        "parent_id": "ai",
    },
    {
        "id": "content-form",
        "label": "内容形式",
        "level": 1,
        "parent_id": None,
    },
    {
        "id": "short-message",
        "label": "短消息",
        "level": 2,
        "parent_id": "content-form",
    },
]
```

标签来源：

- 内容形式：规则生成；
- 一级、二级技术主题：模型只能从配置中选择；
- 与 Embedding 主题关联的标签：可直接从 `matched_topics[*].tag_id` 补充；
- 三级项目或模型名：仅在原文或链接文字中真实出现时允许动态提取。

模型返回未知一级或二级标签时必须丢弃，不得直接写入结果。

### 11.4 内容形式判断

- 普通短推文：短消息；
- 较长正文：长消息；
- arXiv 链接：论文；
- GitHub 仓库链接：项目发布；
- 模型或产品官网：产品发布；
- 引用文章链接：文章推荐。

内容形式标签不需要 LLM 判断。

## 12. 结果存储和审计

### 12.1 原始数据

继续保留：

```text
data/crawler_runs/<run_id>/x/jsonl/search_contents_<date>.jsonl
```

原始数据用于：

- 复现解析问题；
- 阈值变化后重新处理；
- 调试采集字段；
- 不依赖重新调用 Twitter/X。

### 12.2 结构化结果

新增：

```text
data/processed/x.jsonl
```

保存本次所有唯一候选推文，包括：

- 最终保留项；
- 第一层删除项；
- 第二层 shadow_drop 或 drop；
- 第三层删除项；
- 摘要失败但通过退化逻辑的内容；
- 完整 `filter_metadata`。

不保存：

- Embedding 完整向量；
- API Key；
- Cookie；
- 完整回复正文集合；
- 不必要的 Twscrape 原始响应。

一期不再同时维护一份内容重复的独立审计数据库。`data/processed/x.jsonl` 本身就是结构化事实源和筛选审计。

### 12.3 Seen IDs

建议在以下条件均成功后调用 `acknowledge()`：

1. 所有候选项完成应执行的筛选；
2. `data/processed/x.jsonl` 写入成功；
3. `reports/x.html` 原子替换成功。

应确认本次所有已经完成处理的唯一 tweet IDs，包括最终删除项，避免重复消耗 API。

以下情况不 acknowledge：

- Embedding 核心层失败；
- 结构化结果写入失败；
- HTML 写入失败；
- 处理过程发生无法恢复的数据错误。

企业微信通知失败不应回滚已经成功生成的结构化结果和 HTML，也不应导致同一批推文在下一次运行中被重复发送。

## 13. 单平台 HTML

### 13.1 输出文件

Twitter/X 固定生成：

```text
reports/x.html
```

不再生成：

```text
reports/<推文标题>.txt
reports/<推文标题>.html
```

### 13.2 页面数据

渲染器从 `data/processed/x.jsonl` 读取：

- `final_decision=keep`；
- 配置保留期内；
- 按 tweet ID 去重；
- 按 `published_at` 倒序；
- 按配置限制最大展示数量。

### 13.3 每条卡片

至少展示：

- 极简标题；
- abstract；
- 分层标签；
- 作者；
- 发布时间；
- 点赞、回复、转发和浏览量；
- “查看原帖”；
- 可选论文、GitHub、项目或文章链接。

### 13.4 安全要求

- 所有正文、标题、摘要和标签使用 `html.escape`；
- URL 仅允许 `http` 和 `https`；
- 外部链接使用 `target="_blank"`；
- 添加 `rel="noopener noreferrer"`；
- 文件名固定为平台白名单值，不使用推文内容拼接文件名；
- 使用临时文件加原子替换，避免生成半页 HTML。

### 13.5 筛选调试信息

正常页面不展示被删除项。

保留项可以在开发模式下使用折叠区域展示：

- 最高相似主题；
- Embedding 分数；
- 回复样本量；
- 最终 reason code。

完整删除记录仍以 `data/processed/x.jsonl` 为准。

## 14. 企业微信调整

企业微信不再是主流程的强制前置条件。

建议增加：

```python
ENABLE_WECOM = False
```

当启用时：

- 摘要消息中的每条内容直接链接 `source_url`；
- 可额外提供一个 `reports/x.html` 聚合页入口；
- 不再通过 `_output_path` 推导逐条报告地址；
- Webhook 校验只在 `ENABLE_WECOM=True` 时执行。

## 15. 文件级改动

| 文件 | 改动 |
| --- | --- |
| `config.py` | 增加 Twitter 平台规则、Embedding 配置、兴趣主题、标签树、回复阈值、输出保留期和可选企业微信开关；删除旧评分和报告配置。 |
| `crawler/base.py` | 如有需要，增加轻量的可选回复提供能力；不要建立复杂插件体系。 |
| `crawler/twscrape_bridge.py` | 补充引用、回复、转推、敏感标记、hashtags、展开链接和多关键词命中；新增按 tweet ID 读取有限回复的方法。 |
| `utils/parser.py` | 集中完成 Twitter 标准化，输出统一字段和空 `filter_metadata`。 |
| `analyzer/filter.py` | 重写为第一层配置化规则筛选，移除博主白名单和 Lingzao 权重。 |
| `analyzer/embedding_filter.py` | 新增批量 Embedding、多主题相似度、主题级阈值、shadow/enforce 和失败处理。 |
| `analyzer/comment_filter.py` | 新增 Twitter replies 采样、加权质疑比例和跳过策略。 |
| `analyzer/enricher.py` | 一次调用生成极简标题、摘要和受控标签。 |
| `analyzer/pipeline.py` | 批量编排三个筛选阶段；不实现平台采集细节。 |
| `utils/result_store.py` | 追加写入和读取 `data/processed/x.jsonl`，替代旧 RadIter 评分日志。 |
| `output/feed_renderer.py` | 确定性生成 `reports/x.html`，不调用模型。 |
| `main.py` | 切换为新批处理流程，增加 Embedding 专用退出状态和新的 acknowledge 时机。 |
| `notifier/wecom.py` | 改为可选通知并直接链接原帖。 |
| `server.py` | 原则上继续复用，仅在需要平台首页时做小范围调整。 |
| `README.md` | 更新项目目标、Twitter 准备方式、处理流程、输出和风险说明。 |

应停止运行时引用并在整体切换完成后删除：

- `analyzer/lingzao_adapter.py`
- `analyzer/scorer.py`
- `analyzer/ral.py`
- 旧 `output/generator.py`
- 旧 `utils/raditer.py`

Reddit 和 MediaCrawler 采集器可以暂时保留，但一期主流程只正式支持：

```python
CRAWL_PLATFORM = "x"
```

## 16. 分阶段实施方案

不建议一次提交完成全部重构。各阶段应保持可测试、可回退。

### 阶段 0：冻结现状

- 记录当前 34 个测试全部通过的基线；
- 保留当前 Twitter 真实烟雾测试说明；
- 确认工作区中不提交 `.local/x/twscrape.db`；
- 确认真实 Cookie、API Key 和 Webhook 不出现在测试或日志中。

### 阶段 1：Twitter 标准化与第一层规则

范围：

- 补充 Twscrape 字段；
- 合并 `matched_keywords`；
- 建立统一字典结构；
- 重写第一层规则；
- 写入第一层 `filter_metadata`；
- 暂时仍可接旧后续流程进行过渡验证。

验收：

- 短推文不会因旧的 100 字规则被无效删除；
- 回复、转推、引用和敏感内容可区分；
- 展开链接正确；
- 第一层删除原因完整。

### 阶段 2：只实现 Embedding

范围严格限定为：

- `config.py` Embedding 配置；
- `analyzer/embedding_filter.py`；
- 第一层之后的批量接入；
- `filter_metadata`；
- Embedding 错误码和不 acknowledge；
- `tests/test_embedding_filter.py`。

本阶段不要顺手重写：

- 回复筛选；
- 摘要；
- 标签；
- HTML；
- 企业微信。

默认使用 `shadow` 模式。

### 阶段 3：回复区筛选

- 在第二层之后按需调用 `tweet_replies`；
- 加入回复数量、不同作者、点赞加权和明确质疑规则；
- 回复接口不可用时记录 skip；
- 增加模拟 Twscrape replies 的测试；
- 不使用真实网络测试。

### 阶段 4：极简摘要和标签

- 删除 Lingzao 和主观 AI 评分调用；
- 一次模型调用完成标题、摘要和受控标签；
- 加入本地退化逻辑；
- 标签与 Embedding 主题关联；
- 确保只为最终保留项调用模型。

### 阶段 5：结构化存储与单平台 HTML

- 增加 `data/processed/x.jsonl`；
- 增加 `reports/x.html`；
- 修改 acknowledge 时机；
- 企业微信改为可选并直接链接原帖；
- 停止逐条 TXT/HTML；
- 删除旧输出和 RadIter 流程。

### 阶段 6：清理和正式启用

- 更新 README；
- 移除旧 Lingzao、scorer、RAL 和 generator；
- 使用 shadow 数据人工校准每个兴趣主题阈值；
- 将 `EMBEDDING_FILTER_MODE` 改为 `enforce`；
- 运行完整测试集和小规模真实只读烟雾测试。

## 17. 测试方案

### 17.1 Embedding 单元测试

新增：

```text
tests/test_embedding_filter.py
```

至少覆盖：

1. `build_embedding_text` 正确组合正文、引用内容和外链域名；
2. 不把点赞量、回复量、转发量和浏览量放入输入；
3. 不加入无意义用户名；
4. hashtag 去重；
5. 文本长度限制；
6. 不修改原始 content；
7. 余弦相似度计算正确；
8. 零向量安全处理；
9. 维度不一致时报错；
10. 非法向量元素时报错；
11. 一条推文分别计算多个主题分数；
12. 正确选择最高相似主题；
13. 每个主题使用自己的阈值；
14. 任一主题达标即可通过；
15. `matched_topics` 完整；
16. shadow 低分项不被正式删除；
17. enforce 低分项被删除；
18. `filter_metadata` 字段完整；
19. 分数保留四位；
20. 比较阈值时使用未四舍五入数值；
21. 单条空文本不调用 API；
22. 第一层无通过项时不调用 API；
23. 多条推文使用批量 API；
24. 主题描述在一次运行中只生成一次向量；
25. 通过 response index 正确恢复顺序；
26. index 重复或缺失时报错；
27. API 返回数量不一致时报错；
28. API 失败时主流程非零退出；
29. API 失败时不 acknowledge；
30. metadata 和日志不包含完整向量、API Key 或 Cookie。

所有外部 API 必须 mock。

### 17.2 第一层测试

- 普通短推文通过；
- 纯 `@mention` 噪声删除；
- 有外链的短项目发布保留；
- 回复默认删除；
- 转推默认删除；
- 引用推文保留；
- 敏感内容删除；
- 语言配置生效；
- 排除词命中；
- 相同正文和相同外链去重；
- 多关键词命中合并。

### 17.3 回复区测试

- 无回复时保留；
- 少量回复时保留并降低证据置信度；
- 少量负面回复不删除；
- 大量不同作者的高赞明确质疑触发删除；
- 原作者回复不进入负面比例；
- 同一作者重复回复不会放大作者数量；
- 回复 API 失败时记录 `REPLIES_UNAVAILABLE`；
- 回复 API 失败不影响其他推文；
- 不抓取超过配置数量。

### 17.4 摘要和标签测试

- 只为最终保留项调用模型；
- 标题长度限制；
- abstract 为 1～2 句；
- 未知受控标签被拒绝；
- Embedding 主题能映射到标签；
- 动态三级实体必须出现在正文或链接文字中；
- 模型失败时使用本地退化逻辑。

### 17.5 HTML 和状态测试

- 一次运行只生成或更新 `reports/x.html`；
- 不生成逐条 TXT/HTML；
- 所有主链接指向原始推文；
- 引用链接使用展开 URL；
- HTML 正确转义恶意文本；
- 删除项不进入页面；
- `data/processed/x.jsonl` 包含所有候选项；
- HTML 写入失败时不 acknowledge；
- Embedding 失败时不 acknowledge；
- 企业微信失败不重复处理已经成功落盘的推文。

### 17.6 回归测试

每个阶段都运行：

```bash
python -m unittest discover -s tests -v
```

确保现有 Twitter 采集、Parser、主流程和其他平台测试不被破坏。

## 18. 退出状态和失败级别

建议明确区分：

| 类型 | 处理 |
| --- | --- |
| 配置无效 | 主流程失败，不采集或不 acknowledge |
| Twitter 搜索失败 | 主流程失败 |
| 本次没有新推文 | 返回现有无数据状态 |
| 第一层全部删除 | 正常完成，输出空页面或保留旧聚合页 |
| Embedding 核心层失败 | 主流程失败，不 acknowledge |
| 回复接口失败 | 单条或第三层 skip，主流程继续 |
| 摘要模型失败 | 使用本地退化，不删除 |
| 结构化结果写入失败 | 主流程失败，不 acknowledge |
| HTML 写入失败 | 主流程失败，不 acknowledge |
| 企业微信失败 | 记录通知失败，不回滚已落盘结果 |

## 19. 验收标准

一期完成时应满足：

1. 主流程正式支持 Twitter/X 单平台新流程；
2. 每条采集到的唯一候选推文都有结构化记录；
3. 每条记录都有原始推文 URL；
4. 第一层规则配置化并适合短消息；
5. 第一层删除项不调用 Embedding；
6. 每条第一层通过项与所有兴趣主题比较；
7. 每个主题使用自己的阈值；
8. Embedding 默认支持 shadow，校准后支持 enforce；
9. 不在任何位置保存完整向量；
10. Embedding 失败时非零退出且不 acknowledge；
11. 第二层 enforce 删除项不抓回复；
12. 回复少或回复不可用不会直接删除推文；
13. 明确的大规模质疑有可审计的删除逻辑；
14. 最终保留项拥有极简标题、摘要和分层标签；
15. 摘要不进行深度分析或评价；
16. 所有保留和删除项都写入 `data/processed/x.jsonl`；
17. 最终只生成一个 `reports/x.html`；
18. 页面点击直接进入原始推文或引用来源；
19. 不再生成逐条研报；
20. 不再运行 Lingzao、主观 AI 评分和 RAL；
21. 企业微信不再是主流程的必填条件；
22. 全部单元测试和现有回归测试通过。

## 20. 主要风险与控制措施

### 20.1 Twscrape 接口不稳定

控制：

- 固定已测试版本；
- 搜索失败明确返回非零；
- replies 失败允许 skip；
- 限制每条推文的回复数量；
- 不自动扩充账号或绕过平台验证。

### 20.2 Embedding 阈值过度筛选

控制：

- 默认 shadow；
- 保存所有主题分数；
- 每主题独立阈值；
- 先人工校准真实数据；
- 阈值配置化；
- 保留原始 JSONL，允许离线重新判断。

### 20.3 回复区误判

控制：

- 只识别明确质量质疑词；
- 要求多个不同作者；
- 同时考虑回复比例和点赞权重；
- 使用较高删除门槛；
- 保存 reason code 和有限证据；
- 回复少时不删除。

### 20.4 模型生成错误

控制：

- 标题和摘要只在最终阶段生成；
- 标签受配置约束；
- 三级实体必须能在原文验证；
- 模型失败使用本地退化；
- 模型结果不影响已经完成的筛选分数。

### 20.5 状态确认导致数据丢失

控制：

- Embedding、结果存储和 HTML 成功后才 acknowledge；
- 关键失败不写 seen IDs；
- 处理结果保留原始 tweet ID；
- HTML 使用原子替换。

## 21. 最终建议

实施时应优先完成“标准化数据边界 + 第一层 + 独立 Embedding 模块”，再接回复、摘要和 HTML。

Embedding 阶段尤其应保持单一职责：

- 不同时改评论；
- 不同时改摘要；
- 不同时改 HTML；
- 不同时改企业微信；
- 不引入缓存、数据库或任务队列。

这样既能尽快得到真实 Twitter 推文的主题相似度分布，又能避免整个项目在一次大改中失去可验证性。
