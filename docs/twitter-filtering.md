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

通过本地规则后，Embedding 层目前直接跳过，最后再根据回复区是否存在多来源的
强烈质疑进行筛选。

```text
X Top 搜索
  → 数据标准化
  → 第一层：本地规则、技术评分和互动门槛
  → 第二层：Embedding（当前关闭）
  → 第三层：回复区可信度检查
  → LLM 标题、摘要和标签（不参与筛选）
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
CRAWL_LIMIT = 100
TWSCRAPE_LOOKBACK_HOURS = 168
```

- 每个查询最多读取 50 条；
- 所有查询合并、去重后，本次最多进入下游 100 条；
- 只接受最近 168 小时内的帖子；
- 已经确认处理过的帖子 ID 会由 twscrape 状态文件排除。

这里的 100 是候选上限，不是最终必须保留的数量。最终数量完全由筛选结果决定。

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

### 4.6 营销内容扣分

以下内容会扣 2 分：

- course、webinar、conference、event、hackathon；
- newsletter、subscribe、top 10、recommended、follow；
- 课程、直播、论坛、大会、峰会；
- 推荐、关注、清单、合集、招聘、offer。

营销扣分不是硬删除。如果帖子同时提供真实 GitHub/arXiv 证据和足够的技术细节，
仍可能达到及格线。

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

通过技术评分后，还必须满足至少一个互动条件：

```python
"min_view_count": 50
"min_social_engagement": 2
```

也就是：

```text
浏览量 >= 50
或者
点赞 + 回复 + 转发 + 引用 + 收藏 >= 2
```

两项都不满足时使用：

```text
TWITTER_RULE_LOW_ENGAGEMENT
```

使用“二选一”而不是同时满足，是为了保留小众但有真实互动的技术内容，也允许浏览量
较高但互动暂时较少的内容。

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

当前 Embedding 层已关闭：

```python
TWITTER_EMBEDDING_ENABLED = False
```

原因是当前 API 没有可用的 Embedding 模型或渠道。关闭后：

- 不创建 Embedding 客户端；
- 不发送 Embedding API 请求；
- 不计算主题向量相似度；
- 通过第一层的内容直接进入回复区检查；
- 审计记录中明确写入：

```text
TWITTER_EMBEDDING_DISABLED
```

`shadow` 和 `enforce` 配置只有重新启用 Embedding 后才生效。

## 8. 第三层：回复区检查

回复区检查的目标不是判断主题相关性，而是发现多来源、较高置信度的强烈质疑。

当前配置：

```python
"max_replies": 20
"min_sample_size": 5
"min_critical_authors": 3
"critical_ratio_threshold": 0.4
"weighted_ratio_threshold": 0.6
```

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

## 9. LLM 摘要不参与筛选

三层筛选完成后，`analyzer/twitter_enricher.py` 才会调用 Chat API 生成：

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

## 10. 审计数据

每条候选内容都会写入：

```text
data/processed/x.jsonl
```

保留和淘汰内容都会保存，便于查看具体原因。核心结构：

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
          "social_engagement": 20
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
  }
}
```

HTML 只展示最终保留的内容：

```text
reports/x.html
```

## 11. 常见第一层原因码

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
| `TWITTER_RULE_TOPIC_NOT_RELEVANT` | 没有命中 AI 主题 |
| `TWITTER_RULE_CONTENT_TOO_SHORT` | 有效正文过短 |
| `TWITTER_RULE_TECHNICAL_SIGNAL_MISSING` | 有 AI 主题但没有技术信号或证据 |
| `TWITTER_RULE_TECHNICAL_SCORE_TOO_LOW` | 技术得分低于 3 |
| `TWITTER_RULE_LOW_ENGAGEMENT` | 浏览和互动均未达标 |
| `TWITTER_RULE_DUPLICATE_CONTENT` | 正文重复 |
| `TWITTER_RULE_DUPLICATE_EXTERNAL_URL` | 外部链接重复 |
| `TWITTER_RULES_PASSED` | 第一层全部通过 |

## 12. 如何调节严格程度

### 想让筛选更严格

- 提高 `min_technical_score`；
- 提高 `min_view_count` 或 `min_social_engagement`；
- 缩小 `required_topic_keywords`；
- 把不需要的业务领域加入商业或营销扣分词；
- 将某些绝对不接受的内容加入 `exclude_keywords`；
- 只保留带 GitHub/arXiv 等证据的内容。

### 想让筛选更宽松

- 降低 `min_technical_score`；
- 降低互动门槛；
- 扩充技术词和深度技术词；
- 减少商业和营销扣分词；
- 增加搜索查询覆盖范围。

修改规则后应先使用已有 JSONL 做离线复筛，再进行新一轮联网抓取，避免频繁调整导致
结果难以比较。

## 13. 当前限制

1. 关键词规则无法完全理解上下文，仍可能出现误判；
2. GitHub/arXiv 链接只能证明有一手入口，不能证明内容本身正确；
3. 互动数据会偏向发布时间更早、账号粉丝更多的帖子；
4. `Top` 搜索可能牺牲最新内容；
5. 回复数量不足时采用保守放行，不能作为强质量证明；
6. Embedding 当前关闭，无法做语义相似度判断；
7. Chat API 当前不稳定，摘要可能回退为原文；
8. 当前不设置中英文比例，也不设置固定保留数量。

如果后续 API 提供稳定的 Embedding 或 Chat 分类能力，可以在现有确定性规则之后增加
语义复核，但不应替代当前可解释、可审计的本地筛选。

## 14. 相关文件

| 文件 | 作用 |
| --- | --- |
| `config.py` | 搜索、技术评分、互动和回复区配置 |
| `crawler/twscrape_bridge.py` | X 搜索、数量限制和原始数据采集 |
| `utils/twitter_parser.py` | Twitter 数据标准化 |
| `analyzer/twitter_rules.py` | 第一层确定性规则和技术评分 |
| `analyzer/twitter_embedding.py` | 第二层 Embedding 实现，当前未启用 |
| `analyzer/twitter_comments.py` | 第三层回复区筛选 |
| `analyzer/twitter_pipeline.py` | 三层顺序编排 |
| `analyzer/twitter_enricher.py` | 筛选后的标题、摘要和标签 |
| `utils/twitter_result_store.py` | JSONL 审计记录 |
| `output/twitter_feed.py` | 聚合 HTML 生成 |
| `workflows/twitter.py` | Twitter 独立工作流入口 |
