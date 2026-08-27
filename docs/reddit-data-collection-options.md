# Reddit 信息采集方式简析

## 1. 文档状态

- 目的：记录 Reddit 信息采集方案及取舍。
- 当前结论：优先采用 Reddit 公开 JSON 页面。
- 实现状态：已接入 Reddit JSON 采集器；不修改现有 Twitter 筛选和 HTML 输出流程。

## 2. 可选方式

### 2.1 官方 Data API / PRAW

通过 Reddit OAuth Data API，并使用 PRAW 等官方 API 客户端采集。

优点：

- 字段完整，包括正文、作者、发布时间、社区、分数、点赞比例、评论数和标签等；
- 接口结构相对明确，适合分页、搜索和长期运行；
- PRAW 封装成熟，开发成本较低。

缺点：

- 需要申请并获得 Reddit API 访问权限；
- 当前新应用审核较严格，等待时间不可控；
- 凭证和获批用途不可随意转让或共享；
- 不适合作为本项目近期上线的前置依赖。

### 2.2 Reddit 公开 JSON 页面

在公开 Reddit 页面 URL 后使用 `.json`，直接读取 JSON，例如：

```text
https://www.reddit.com/r/LocalLLaMA/new.json?limit=20
```

优点：

- 不需要 API token；
- 返回结构化 JSON，解析简单；
- 字段与 PRAW 接近，通常包含 `id`、`title`、`selftext`、`author`、
  `created_utc`、`subreddit`、`permalink`、`score`、`upvote_ratio`、
  `num_comments`、`link_flair_text` 和 `domain`；
- 容易转换成项目现有的统一 JSONL 格式；
- 适合个人电脑上的低频、小规模采集。

缺点：

- 匿名访问不是具有稳定性承诺的正式 API；
- 不同网络环境可能出现 `403` 或 `429`；
- Reddit 可能随时调整字段、限流或访问规则；
- 全站搜索入口通常比指定 subreddit 的 `new.json` 更不稳定；
- 不适合高并发、大规模抓取或要求 SLA 的在线服务。

### 2.3 RSS

通过 subreddit 的 RSS/Atom feed 获取最新帖子。

优点：

- 不需要 API token；
- 格式标准，实现成本低；
- 适合仅监控少量社区的最新内容。

缺点：

- 通常缺少分数、点赞比例、评论数、标签和 NSFW 等字段；
- 正文可能是 HTML，需要额外清洗；
- 搜索、分页和历史回溯能力较弱；
- 同样可能受到严格限流。

本项目不采用 RSS，以避免维护第二套字段不完整的采集逻辑。

### 2.4 授权第三方数据服务

通过 Reddit 官方数据合作伙伴或社交聆听平台购买数据访问。

优点：

- 更适合商业使用、近实时数据和长期稳定运行；
- 部分服务可以提供帖子、评论、互动指标和历史数据。

缺点：

- 通常面向企业客户，价格和采购周期较高；
- 不一定允许通过 API 导出全文；
- 数据保存、再分发和 LLM 分析权限需要在合同中单独确认。

## 3. 当前建议

本项目近期采用公开 JSON 页面，原因是：

1. 目标是在个人电脑本地运行，而不是部署到云服务器；
2. 采集规模较小，不需要高并发或完整历史数据；
3. JSON 字段比 RSS 完整，并且更容易接入现有处理流程；
4. 不依赖暂时难以获得的 Reddit API 审核结果。

建议按明确的 subreddit 拉取最新帖子，再在本地按关键词、时间窗口和帖子 ID
执行筛选与去重：

```text
指定 subreddit 的 new.json
→ 标准化字段
→ 本地关键词筛选
→ 时间窗口筛选
→ ID 去重
→ 输出统一 JSONL
→ 进入现有筛选和 HTML 输出流程
```

不建议依赖全站搜索，也不加入 RSS fallback，以保持实现简单。

## 4. 实现约束

- 使用固定且如实标识项目的 `User-Agent`，不伪装浏览器；
- 设置请求超时，并对 `403`、`429` 和非 JSON 响应给出明确错误；
- 遇到 `429` 时报告 `Retry-After` 并停止本次运行，不进行无限重试；
- 每个 subreddit 每次只获取业务所需的少量最新内容；
- 保留原帖链接和作者信息；
- 不使用登录 Cookie、代理轮换或 IP 切换；
- 在另一台电脑正式运行前，先执行独立烟雾测试；
- JSON 原始字段先在 Reddit bridge 中标准化，后续筛选和输出模块不区分采集来源。

## 5. 风险说明

公开 JSON 解决的是近期技术接入问题，不代表 Reddit 对该方式提供长期兼容性或商业
使用授权。若项目未来转为商业产品、云端服务或大规模采集，应重新评估官方 Data API
或授权数据供应商。

参考：

- [Reddit Developer Platform & Accessing Reddit Data](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data)
- [Reddit Developer Terms](https://redditinc.com/policies/developer-terms)
