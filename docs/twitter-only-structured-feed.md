# Twitter 独立结构化信息流方案

> 本文记录最初的结构化信息流设计。当前实际筛选规则、技术评分、互动门槛和
> Embedding 开关请以 [`twitter-filtering.md`](twitter-filtering.md) 为准。

## 1. 改造边界

本次改造只作用于 Twitter/X。

- 小红书和知乎继续使用 `MediaCrawlerBridge` 采集。
- 小红书和知乎继续使用原有 Parser、Lingzao、规则过滤、博主权重、
  AI 评分、RAL、逐条报告和企业微信流程。
- Twitter 继续使用 `TwscrapeBridge` 采集，但使用独立的标准化、筛选、
  摘要、标签、存储和聚合页模块。
- 后续平台不得因为接入统一采集接口而自动进入 Twitter 流程。是否迁移到新流程
  必须由平台路由显式决定。

主入口只做一次清晰分流：

```text
platform == "x"  -> workflows/twitter.py
其他平台          -> main.py 中的原有工作流
```

## 2. Twitter 处理流程

```text
twscrape 采集
  -> Twitter 专用标准化
  -> 第一层规则筛选
  -> 第二层多主题 Embedding 筛选
  -> 第三层回复区筛选
  -> 极简标题、摘要和分层标签
  -> data/processed/x.jsonl
  -> reports/x.html
  -> 可选企业微信通知
```

第一层未通过的内容不调用 Embedding。Embedding 失败时本次流程返回非零状态，
不写入结果、不更新 HTML，也不确认 twscrape 的 seen IDs。回复区不可用时记录跳过
原因，不让整个流程失败。

## 3. 数据与审计

Twitter 标准化结果保留以下核心字段：

- `id`、`platform_item_id`、`platform`
- `title`、`content`、`quoted_content`、`abstract`
- `tags`、`entities`
- `source_url`、`referenced_urls`
- `published_at`、`author`、`username`、`metrics`
- `platform_metadata`
- `filter_metadata`
- `processed_at`

`filter_metadata.stages` 按顺序记录规则、Embedding 和回复筛选结果。每个阶段包含
决定、原因码和必要的调试数据；不保存完整 Embedding 向量、Cookie 或 API Key。
最终决定使用 `keep` 或 `drop`。

`data/processed/x.jsonl` 保存保留和删除记录，便于回看筛选原因。`reports/x.html`
只展示当前保留项，主按钮直接链接 `source_url`，不再为 Twitter 生成逐条二次研报。

## 4. Embedding 判断

兴趣主题、主题描述、标签映射和主题阈值都由 `config.py` 配置。一次运行中先批量生成
主题向量，再按批次生成推文向量。

每条推文与所有主题计算余弦相似度，并记录各主题分数。最终由最高相似主题及其自身
阈值决定：

- 达到最高主题阈值：`pass`
- 未达到且为 `shadow`：记录 `shadow_drop`，继续后续流程
- 未达到且为 `enforce`：正式 `drop`

第一版默认 `shadow`，先积累真实分数分布后再调整阈值和切换 `enforce`。

## 5. 模块职责

| 模块 | 职责 |
| --- | --- |
| `utils/twitter_parser.py` | 只标准化 twscrape 当前运行数据 |
| `analyzer/twitter_rules.py` | Twitter 低成本确定性规则 |
| `analyzer/twitter_embedding.py` | 多主题 Embedding 和阈值判断 |
| `analyzer/twitter_comments.py` | 回复区基础质量信号 |
| `analyzer/twitter_enricher.py` | 极简摘要和受控分层标签 |
| `analyzer/twitter_pipeline.py` | 三层筛选顺序编排 |
| `utils/twitter_result_store.py` | Twitter JSONL 事实记录 |
| `output/twitter_feed.py` | 固定生成 `reports/x.html` |
| `workflows/twitter.py` | Twitter 运行和失败边界 |

这些模块不注册全局插件，不引入抽象基类或数据库。未来增加平台时，可复用明确合适的
纯函数，但不应直接把其他平台路由到 Twitter 模块。

## 6. 验收重点

- 小红书和知乎仍调用原有完整工作流。
- Twitter 不调用旧的 Lingzao、评分、RAL 和逐条报告模块。
- 规则删除后不调用 Embedding 或回复接口。
- 每个主题有独立阈值，最高主题使用自己的阈值做最终判断。
- 回复样本不足不直接删除；明确且多来源的强质疑才删除。
- 所有删除和跳过决定都有原因码。
- HTML 转义不可信文本，只接受有效 HTTP/HTTPS 链接。
- 写入和 HTML 生成成功后才确认本次 twscrape 状态。
