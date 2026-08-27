# Reddit RSS 采集说明

## 结论

本分支采用 subreddit 的最新帖子 Atom feed：

```text
https://www.reddit.com/r/LocalLLaMA/new/.rss?limit=100
```

2026-07-24 在当前开发机进行的真实测试结果：

- 普通 Reddit 页面：HTTP 200；
- 匿名 `new.json`：HTTP 403；
- `new/.rss`：HTTP 200，类型为 `application/atom+xml`；
- 第一次 RSS 响应显示额度剩余为 0、约 30 秒重置，紧接着请求会返回 429。

因此 RSS 能解决当前机器的 JSON 403，但不代表它没有限流或长期稳定性风险。PR #9
继续单独保留 JSON 实验，本分支不包含或依赖 PR #9。

## 数据范围

RSS 可稳定读取：

- 帖子 ID；
- 标题；
- 自帖正文 HTML，并转换为纯文本；
- 作者；
- subreddit；
- 发布时间；
- 原帖链接；
- RSS 中出现的外部链接和缩略图。

RSS 不提供：

- score；
- upvote ratio；
- 评论数；
- flair；
- NSFW 等完整帖子属性；
- 评论正文。

程序不会猜测这些指标。统一 JSONL 中对应互动指标写为 `null`，同时写入
`metrics_available: false`；现有解析器会把缺失互动数标准化为 0。

## 采集流程

```text
明确 subreddit 的 new/.rss
→ Atom XML 校验
→ 正文 HTML 转纯文本
→ 时间窗口筛选
→ 帖子 ID 去重
→ 记录本地关键词命中（不淘汰）
→ 统一 JSONL
→ Reddit 内容与来源规则
→ Reddit 多主题 Embedding
→ Reddit 五维质量评分
→ 按质量分排序并限制最终候选数
→ 极简标题和摘要
→ data/processed/reddit.jsonl
→ reports/reddit.html
→ 可选企业微信短摘要与 Reddit 原帖直链
```

关键词匹配只在本地进行并写入审计字段，不作为采集阶段的淘汰条件，也不使用 Reddit
搜索 feed。默认每个社区请求 `limit=100`，但 RSS 服务端实际返回数量可能更少；
`REDDIT_RSS_MAX_CANDIDATES = 0` 表示不在专用 pipeline 前设置跨社区总量上限。
默认只配置 `LocalLLaMA` 一个社区；配置多个社区时，采集器会在请求之间至少等待
31 秒，并根据响应中的 `x-ratelimit-reset` 延长等待。

## 专用筛选与评分

Reddit 不再进入小红书/知乎使用的互动质量和博主画像层。专用 pipeline 分为：

1. 内容与来源规则：校验 Reddit 来源、RSS 采集方式、帖子 ID、URL、subreddit、
   最低内容长度和批次内重复项；
2. 主题 Embedding：比较标题、正文、subreddit 和外部来源域名与
   `REDDIT_INTEREST_TOPICS`；
3. 质量评分：按主题相关性 35%、信息深度 25%、证据可追溯性 20%、时效性 10%、
   来源完整性 10% 计算 0–10 分；
4. 末端排序：按质量分降序排列，在全部筛选完成后保留
   `REDDIT_FINAL_RESULT_LIMIT` 条最终候选。

质量评分始终写入 `interaction_metrics_used: false`。即使将来其他采集器提供互动数据，
也不会在没有显式设计和校准的情况下改变 RSS 内容得分。

## 专用输出与通知

Reddit 不进入通用的逐条文本卡片、长 HTML 研报、COS 上传或
`REPORT_BASE_URL` 通知链路：

- 全部候选及其筛选审计追加保存到 `data/processed/reddit.jsonl`；
- 通过筛选的最新帖子聚合展示在固定页面 `reports/reddit.html`；
- 每条内容只保留极简标题、短摘要、质量分、社区、主题和原帖链接；
- 企业微信通知默认最多包含 5 条完整帖子，不会把某条内容从中间截断；
- 整条消息按 UTF-8 控制在 4096 字节以内，主链接直接跳转 Reddit 原帖；
- 摘要模型失败时使用本地确定性降级，不会再生成“研报失败”的 HTML。

如不需要企业微信通知，可设置 `REDDIT_ENABLE_WECOM=False`。结构化 JSONL、聚合页面和
采集状态确认仍会正常执行。

## 运行

先进行只读烟雾测试：

```bash
.venv/bin/python scripts/smoke_test_reddit_rss.py "model" \
  --subreddit LocalLLaMA --limit 3
```

测试通过后设置：

```python
CRAWL_PLATFORM = "reddit"
REDDIT_RSS_SUBREDDITS = ["LocalLLaMA"]
REDDIT_RSS_KEYWORDS = ["LLM", "model", "agent", "inference"]
REDDIT_RSS_RESULTS_PER_SUBREDDIT = 100
REDDIT_RSS_MAX_CANDIDATES = 0
REDDIT_FINAL_RESULT_LIMIT = 20
REDDIT_ENABLE_WECOM = True
```

然后运行：

```bash
.venv/bin/python main.py --check-config
.venv/bin/python main.py
```

烟雾测试不会确认已处理状态，可以重复测试同一批帖子。

## 约束与风险

- 使用如实标识项目的固定 User-Agent；
- 不使用 OAuth、PRAW、登录 Cookie、代理或 IP 轮换；
- 每个社区每轮只发出一次请求；
- 遇到 429 不重试当前社区，并显示建议等待时间；
- 响应不是 Atom XML、体积异常或字段缺失时明确失败；
- RSS 的字段和访问规则可能变化；
- 如未来需要互动指标、评论、大规模采集或稳定 SLA，应改用获得授权的数据接口。
