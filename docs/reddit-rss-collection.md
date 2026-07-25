# Reddit RSS 采集说明

## 结论

本分支采用 subreddit 的最新帖子 Atom feed：

```text
https://www.reddit.com/r/LocalLLaMA/new/.rss?limit=10
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
→ 本地关键词筛选
→ 时间窗口筛选
→ 帖子 ID 去重
→ 统一 JSONL
→ 现有非 Twitter 分析与输出流程
```

关键词筛选只在本地进行，不使用 Reddit 搜索 feed。默认只配置
`LocalLLaMA` 一个社区；配置多个社区时，采集器会在请求之间至少等待 31 秒，并根据
响应中的 `x-ratelimit-reset` 延长等待。

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
