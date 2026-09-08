# Twitter/X 当前筛选机制

本文档说明 AI Content Miner 当前如何搜索、筛选并输出 Twitter/X 内容。
内容以仓库中的实际运行代码为准，适用于 `CRAWL_PLATFORM = "x"` 的独立
Twitter 工作流。

## 1. 一句话说明

当前机制先通过高技术意图的 X 搜索获得候选内容，再使用本地确定性规则检查：

1. 数据是否有效；
2. 是否真正命中 AI 主题；
3. 是否包含足够的技术信息；
4. 是否有 GitHub、arXiv 等一手证据；
5. 是否属于商业新闻、营销或招聘内容；
6. 是否具备最低互动质量；
7. 是否与本次其他内容重复。

通过本地规则和可选 Embedding 后，系统先对全部合格候选做事件聚类和排序，再按
排名惰性检查回复区，直到选出最多 8 条每日精选。

```text
X Top 搜索
  → 数据标准化
  → 第一层：本地规则、技术评分和互动门槛
  → 第二层：Embedding（默认关闭）
  → 同事件聚类、内容排序和多样性约束
  → 按排名惰性检查回复区并补位
  → 最多 8 条每日精选
  → 仅为入选内容生成 LLM 标题、摘要和标签
  → data/processed/x.jsonl
  → reports/x.html
```

## 2. 搜索阶段

### 2.1 搜索模式

当前使用 X 的 `Top` 搜索，而不是 `Latest`：

```python
TWSCRAPE_SEARCH_PRODUCT = "Top"
```

`Top` 更容易返回已有浏览和互动的帖子，可以减少刚发布、零浏览、零互动的低质量
内容。但它不保证技术相关性，因此搜索结果仍必须经过本地筛选。

### 2.2 搜索查询

当前不再单独搜索过于宽泛的 `"大模型"` 或 `"LLM"`，而是使用带技术意图的
组合查询：

```python
SEARCH_KEYWORDS = [
    '"AI Agent" (framework OR benchmark OR "tool calling" OR MCP OR GitHub)',
    '"LLM" (training OR inference OR benchmark OR architecture OR quantization)',
    '"reinforcement learning" (paper OR benchmark OR implementation OR code)',
    '("大模型" OR LLM) (训练 OR 推理 OR 架构 OR 评测 OR 量化 OR 微调 OR 开源)',
    '("AI Agent" OR 智能体) (框架 OR 工具调用 OR MCP OR 开源 OR 实现)',
]
```

搜索阶段只负责提高候选集的相关性，不能代替后续筛选。X 返回某条帖子并不代表
正文一定严格包含完整查询，也不代表它符合项目的技术内容目标。

### 2.3 数量与时间范围

```python
TWSCRAPE_RESULTS_PER_QUERY = 50
TWSCRAPE_LOOKBACK_HOURS = 168
```

- 每个查询最多读取 50 条；
- 所有查询结果都会在合并和去重后进入 Twitter 筛选；
- 只接受最近 168 小时内的帖子；
- 已经确认处理过的帖子 ID 会由 twscrape 状态文件排除。

Twitter 不读取通用的 `CRAWL_LIMIT`。候选不会因为发布时间排在全局第 100 条之后
而被截断，发布数量由后面的每日选择器控制。

## 3. 第一层：本地确定性规则

第一层位于 `analyzer/twitter_rules.py`，不调用 LLM 或 Embedding API。规则按固定
顺序执行，任意一步失败都会立即淘汰，不再执行后续昂贵步骤。

### 3.1 基础数据检查

帖子必须满足：

- 平台为 X；
- 有平台帖子 ID；
- 正文非空；
- 原帖 URL 是有效的 HTTP/HTTPS 地址；
- 有发布时间；
- 不是敏感内容；
- 不是回复或转推；
- 引用推文允许保留。

### 3.2 语言检查

当前允许：

```python
"allowed_languages": ["zh", "en"]
```

没有设置中英文比例，也没有设置每种语言的保留数量。

### 3.3 硬排除词

明显不符合目标的内容会直接淘汰，例如：

- 空投、返利；
- 博彩、赌场、下注；
- giveaway；
- sportsbook、match winner、handicap；
- 招聘。

硬排除词命中后使用原因码：

```text
TWITTER_RULE_EXCLUDED_KEYWORD
```

### 3.4 AI 主题必须命中

正文、引用正文、标签和引用链接文字中，必须至少命中一个 AI 主题词，例如：

- AI Agent、AI Agents、Agentic AI、智能体；
- LLM、Large Language Model、大模型；
- Reinforcement Learning、强化学习；
- Quantitative Trading、量化投资。

X 返回的 `matched_keywords` 不作为本地主题判断依据。项目会重新检查实际内容，
避免把“建模”等宽松搜索结果误认为“大模型”技术内容。

未命中时使用：

```text
TWITTER_RULE_TOPIC_NOT_RELEVANT
```

### 3.5 最低信息量

移除 URL、用户名和装饰字符后，正文至少需要 40 个有效字符：

```python
"min_meaningful_chars": 40
```

短内容如果包含外部引用链接可以例外，避免误删只有简短介绍的项目或论文链接。

未达到要求时使用：

```text
TWITTER_RULE_CONTENT_TOO_SHORT
```

## 4. 技术相关性评分

AI 主题命中只表示“帖子谈到了 AI”，不能证明它包含有价值的技术信息。因此当前
规则还会计算一个可审计的技术得分。

### 4.1 评分公式

| 条件 | 分数 |
| --- | ---: |
| 至少命中一个普通技术词 | +2 |
| 至少命中一个深度技术词 | +1 |
| 包含 GitHub、arXiv、HuggingFace 或 Papers with Code 链接 | +3 |
| 命中商业、资本市场或人事新闻词 | -3 |
| 命中课程、活动、推荐清单等营销词 | -2 |

最终要求：

```python
"min_technical_score": 3
```

技术得分必须至少为 3。

### 4.2 普通技术词

普通技术词用于确认帖子确实涉及技术，例如：

- training、inference、fine-tuning、quantization；
- benchmark、paper、code、dataset；
- framework、implementation、tool calling；
- GitHub、arXiv、HuggingFace、API、MCP、RAG；
- 架构、训练、推理、微调、量化；
- 评测、论文、实验、代码、开源；
- 框架、实现、工具调用、数据集、蒸馏、部署。

如果既没有技术词，也没有一手证据链接，直接淘汰：

```text
TWITTER_RULE_TECHNICAL_SIGNAL_MISSING
```

### 4.3 深度技术词

深度技术词用于区分“泛泛提到训练/开源”和“真正讨论技术细节”。例如：

- architecture、framework、inference；
- fine-tuning、quantization、evaluation；
- benchmark、paper、experiment、code；
- implementation、tool calling、dataset；
- 架构、框架、推理、微调、量化；
- 评测、基准、论文、实验、代码、实现。

例如，“某公司正在训练并开源大模型”只能获得普通技术分；如果没有更具体的架构、
推理、评测、代码或一手来源，无法达到当前及格线。

### 4.4 一手证据加分

以下域名被视为可继续核查的技术证据：

```text
github.com
arxiv.org
huggingface.co
paperswithcode.com
```

命中证据域名不代表内容一定正确，但说明帖子提供了项目、论文、模型或代码入口，
因此获得较高权重。

### 4.5 商业和行业新闻扣分

商业、资本市场、地缘竞争和人事变动会扣 3 分，例如：

- acquisition、funding、valuation、revenue、IPO；
- stock、market cap、capital expenditure、profit；
- 收购、融资、估值、财报、股价、上市；
- 商业化、营收、市值、资本、二级市场；
- 中美、争霸、军备竞赛；
- 升任、任命、人事、部门合并、内部通知。

这类帖子即使出现“LLM、API、训练”等词，也通常无法通过。如果同时提供强技术
细节和一手证据，仍有可能通过，避免把真正的技术分析一刀切删除。

### 4.6 广告硬过滤与软推广扣分

课程、订阅和获客内容不允许进入每日精选。以下高置信度广告词在技术评分前直接淘汰：

- course、webinar、bootcamp、masterclass、newsletter、subscribe；
- gumroad、enroll；
- 课程、开源课、公开课、训练营、报名、订阅；
- 亲授、付费社群、知识星球、免费领取。

对应原因码：

```text
TWITTER_RULE_PROMOTION_NOT_ALLOWED
```

conference、event、follow、推荐、清单和合集等词也可能出现在正常技术分享中，因此
仍作为软推广信号扣分，而不是单独触发硬删除。

### 4.7 评分示例

#### 示例 A：技术讨论

```text
AI Agent framework + tool calling implementation
```

- AI 主题命中：必要条件通过；
- 普通技术词：+2；
- 深度技术词：+1；
- 总分：3；
- 如果互动质量也达标，则保留。

#### 示例 B：商业收购新闻

```text
某公司计划收购 LLM API 服务商，预计提升营收并准备 IPO
```

- 普通技术词：+2；
- 商业新闻：-3；
- 总分：-1；
- 淘汰。

#### 示例 C：项目一手来源

```text
AI Agent project release
https://github.com/example/project
```

- GitHub 一手证据：+3；
- 总分达到及格线；
- 如果其他规则通过，则保留。

#### 示例 D：泛行业观点

```text
中国大模型正在加速商业化，行业竞争进入新阶段
```

- AI 主题命中；
- 没有技术信号或一手证据；
- 直接淘汰。

## 5. 互动质量检查

浏览量只说明帖子获得过曝光，不代表读者认可，因此不能再单独帮助内容通过。系统使用：

```text
加权互动 =
    点赞
  + 1.5 × 回复
  + 3 × 转发
  + 2.5 × 引用
  + 2 × 收藏
```

规则层默认要求加权互动至少达到 2。带 GitHub、arXiv、Hugging Face 或
Papers with Code 链接的内容可以暂时通过这个低成本门槛，让新项目进入后续排序；
最终发布仍要求加权互动至少达到 5。

未达到规则层门槛时使用：

```text
TWITTER_RULE_LOW_ENGAGEMENT
```

每日排序进一步比较绝对互动、互动速度和互动率：

```text
互动质量 =
    50% × 绝对互动分位数
  + 30% × 互动速度分位数
  + 20% × 互动率分位数
```

其中互动速度按帖子年龄衰减，互动率使用加权互动除以浏览量。这样互动已经很高的内容
获得最高优先级，新发布但传播很快的内容也不会只因累计时间短而吃亏。

## 6. 重复内容检查

同一次运行中会排除：

- 有效正文完全相同的帖子；
- 指向同一个外部 URL 的重复帖子。

对应原因码：

```text
TWITTER_RULE_DUPLICATE_CONTENT
TWITTER_RULE_DUPLICATE_EXTERNAL_URL
```

## 7. 第二层：Embedding

Embedding 默认关闭，也可以通过环境变量启用：

```python
TWITTER_EMBEDDING_ENABLED = False
```

关闭后：

- 不创建 Embedding 客户端；
- 不发送 Embedding API 请求；
- 不计算主题向量相似度；
- 通过第一层的内容直接进入回复区检查；
- 审计记录中明确写入：

```text
TWITTER_EMBEDDING_DISABLED
```

`shadow` 和 `enforce` 配置只有重新启用 Embedding 后才生效。

## 8. 回复区检查

回复区检查的目标不是判断主题相关性，而是发现多来源、较高置信度的强烈质疑。

当前配置：

```python
"max_replies": 20
"min_sample_size": 5
"min_critical_authors": 3
"critical_ratio_threshold": 0.4
"weighted_ratio_threshold": 0.6
```

回复检查在每日候选完成聚类和排序后惰性执行。系统从最高排名开始检查，遇到被强烈
质疑的内容就继续检查下一条补位，直到选满 8 条或候选耗尽。

处理原则：

- 回复接口不可用：记录 `skip`，不因接口故障删除原帖；
- 没有有效回复：低置信度通过；
- 回复样本少于 5：低置信度通过；
- 多名不同用户集中指出造假、误导、错误或不可复现：删除；
- 原作者自己的回复、重复回复和 bot 用户会被排除。

常见原因码：

```text
TWITTER_REPLIES_UNAVAILABLE
TWITTER_REPLIES_EMPTY
TWITTER_REPLIES_LOW_SAMPLE
TWITTER_REPLIES_PASSED
TWITTER_REPLIES_STRONG_CHALLENGE
```

## 9. 每日精选选择

每日选择器位于 `analyzer/twitter_daily_selector.py`，负责：

- 合并相同外部链接或标题、实体高度相似的同事件内容；
- 按互动质量 60%、新颖度 15%、一手证据 10%、技术信息 10% 和新鲜度 5% 排序；
- 48 小时以内的内容正常竞争；
- 48 至 168 小时的内容只有互动质量至少达到 0.85 且带一手证据时继续竞争；
- 加权互动低于 5 的内容不用于填充发布名额；
- 最近 7 天已发布的同事件默认不再推送；
- 同一作者每天最多 1 条；
- 同一主题没有硬配额，每多选择一条只在重排时扣 3 分；
- 最多 8 条标记为 `selected`；
- 其余合格内容标记为 `archive` 或 `cluster_duplicate`。

8 条是发布上限，不是填充目标。候选不足时不会降低质量标准凑满配额。HTML 与
企业微信消费同一份 `selected` 列表，因此两端不会出现不同的内容层级或数量。

互动质量是最终顺序的主导因素。主题只做轻量软重排，因此不会再出现四个主题乘以
每类两条、导致每日容量无法用满的问题。

常见每日选择原因码：

```text
TWITTER_DAILY_TOO_OLD
TWITTER_DAILY_LOW_SOCIAL_SIGNAL
TWITTER_DAILY_STALE_LOW_SIGNAL
TWITTER_DAILY_RECENT_EVENT
TWITTER_DAILY_CLUSTER_DUPLICATE
TWITTER_DAILY_AUTHOR_LIMIT
TWITTER_DAILY_NOT_SELECTED
TWITTER_DAILY_SELECTED
```

## 10. LLM 摘要不参与筛选

每日选择完成后，`analyzer/twitter_enricher.py` 只为入选内容调用 Chat API：

- 极简标题；
- 一到两句话摘要；
- 受控技术标签；
- 原文中明确出现的实体。

LLM 结果不会改变 `keep/drop` 决定。API 调用失败时会回退为原文标题和首句摘要，
并记录：

```json
{
  "status": "fallback",
  "error_type": "InternalServerError"
}
```

因此，页面使用原文回退摘要不代表筛选失败，只表示摘要服务不可用。

## 11. 审计数据

每条候选内容都会写入：

```text
data/processed/x.jsonl
```

发布、归档和淘汰内容都会保存，便于查看具体原因。除 `filter_metadata` 外，每条
预筛通过内容还会写入 `publication_metadata`：

```json
{
  "filter_metadata": {
    "stages": [
      {
        "stage": "rules",
        "decision": "pass",
        "reason_codes": ["TWITTER_RULES_PASSED"],
        "details": {
          "technical_score": 6,
          "technical_keywords": ["framework", "tool calling"],
          "technical_depth_keywords": ["framework", "tool calling"],
          "evidence_domains": ["github.com"],
          "business_penalties": [],
          "promotion_penalties": [],
          "view_count": 1000,
          "weighted_engagement": 32.5
        }
      },
      {
        "stage": "embedding",
        "decision": "pass",
        "mode": "disabled",
        "reason_codes": ["TWITTER_EMBEDDING_DISABLED"]
      },
      {
        "stage": "comments",
        "decision": "pass",
        "reason_codes": ["TWITTER_REPLIES_PASSED"]
      }
    ],
    "final_decision": "keep"
  },
  "publication_metadata": {
    "digest_date": "2026-07-29",
    "decision": "selected",
    "score": 83.5,
    "rank": 1,
    "base_rank": 1,
    "selection_score": 83.5,
    "score_breakdown": {
      "social_quality": 0.93,
      "novelty": 1.0,
      "evidence": 1.0,
      "technical": 1.0,
      "freshness": 0.91,
      "promotion_penalty": 0.0
    },
    "topic": "ai-agent"
  }
}
```

HTML 与企业微信都只展示当天同一批最多 8 条精选：

```text
reports/x.html
```

## 12. 常见第一层原因码

| 原因码 | 含义 |
| --- | --- |
| `TWITTER_RULE_WRONG_PLATFORM` | 数据不是 X 内容 |
| `TWITTER_RULE_MISSING_ID` | 缺少帖子 ID |
| `TWITTER_RULE_EMPTY_CONTENT` | 正文为空 |
| `TWITTER_RULE_INVALID_SOURCE_URL` | 原帖 URL 无效 |
| `TWITTER_RULE_MISSING_PUBLISHED_AT` | 缺少发布时间 |
| `TWITTER_RULE_SENSITIVE_CONTENT` | 敏感内容 |
| `TWITTER_RULE_REPLY_NOT_ALLOWED` | 回复帖不允许 |
| `TWITTER_RULE_RETWEET_NOT_ALLOWED` | 转推不允许 |
| `TWITTER_RULE_LANGUAGE_NOT_ALLOWED` | 语言不是中文或英文 |
| `TWITTER_RULE_EXCLUDED_KEYWORD` | 命中硬排除词 |
| `TWITTER_RULE_PROMOTION_NOT_ALLOWED` | 命中课程、订阅或获客广告 |
| `TWITTER_RULE_TOPIC_NOT_RELEVANT` | 没有命中 AI 主题 |
| `TWITTER_RULE_CONTENT_TOO_SHORT` | 有效正文过短 |
| `TWITTER_RULE_TECHNICAL_SIGNAL_MISSING` | 有 AI 主题但没有技术信号或证据 |
| `TWITTER_RULE_TECHNICAL_SCORE_TOO_LOW` | 技术得分低于 3 |
| `TWITTER_RULE_LOW_ENGAGEMENT` | 加权互动未达标且没有一手证据 |
| `TWITTER_RULE_DUPLICATE_CONTENT` | 正文重复 |
| `TWITTER_RULE_DUPLICATE_EXTERNAL_URL` | 外部链接重复 |
| `TWITTER_RULES_PASSED` | 第一层全部通过 |

## 13. 如何调节严格程度

### 想让筛选更严格

- 提高 `min_technical_score`；
- 提高 `min_weighted_engagement` 或 `TWITTER_DAILY_MIN_WEIGHTED_ENGAGEMENT`；
- 提高 `TWITTER_DAILY_FALLBACK_MIN_SOCIAL_SCORE`；
- 缩小 `required_topic_keywords`；
- 把不允许的推广形式加入 `promotion_hard_drop_keywords`；
- 将某些绝对不接受的内容加入 `exclude_keywords`；
- 只保留带 GitHub/arXiv 等证据的内容。

### 想让筛选更宽松

- 降低 `min_technical_score`；
- 降低规则层或发布层的加权互动门槛；
- 扩充技术词和深度技术词；
- 减少商业和营销扣分词；
- 增加搜索查询覆盖范围。

修改规则后应先使用已有 JSONL 做离线复筛，再进行新一轮联网抓取，避免频繁调整导致
结果难以比较。

## 14. 当前限制

1. 关键词规则无法完全理解上下文，仍可能出现误判；
2. GitHub/arXiv 链接只能证明有一手入口，不能证明内容本身正确；
3. 互动数据会偏向发布时间更早、账号粉丝更多的帖子；
4. `Top` 搜索可能牺牲最新内容；
5. 回复数量不足时采用保守放行，不能作为强质量证明；
6. Embedding 当前关闭，无法做语义相似度判断；
7. Chat API 当前不稳定，摘要可能回退为原文；
8. 当前不设置中英文比例；
9. 事件聚类使用确定性文本和链接特征，仍可能漏合并或误合并。

如果后续 API 提供稳定的 Embedding 或 Chat 分类能力，可以在现有确定性规则之后增加
语义复核，但不应替代当前可解释、可审计的本地筛选。

## 15. 相关文件

| 文件 | 作用 |
| --- | --- |
| `config.py` | 搜索、技术评分、互动和回复区配置 |
| `crawler/twscrape_bridge.py` | X 搜索、数量限制和原始数据采集 |
| `utils/twitter_parser.py` | Twitter 数据标准化 |
| `analyzer/twitter_rules.py` | 第一层确定性规则和技术评分 |
| `analyzer/twitter_engagement.py` | 规则层和排序层共用的加权互动计算 |
| `analyzer/twitter_embedding.py` | 第二层 Embedding 实现，当前未启用 |
| `analyzer/twitter_comments.py` | 第三层回复区筛选 |
| `analyzer/twitter_daily_selector.py` | 每日聚类、排序、回复补位和最多 8 条选择 |
| `analyzer/twitter_pipeline.py` | 三层顺序编排 |
| `analyzer/twitter_enricher.py` | 筛选后的标题、摘要和标签 |
| `utils/twitter_result_store.py` | JSONL 审计记录 |
| `output/twitter_feed.py` | 聚合 HTML 生成 |
| `workflows/twitter.py` | Twitter 独立工作流入口 |
