"""只测试 Reddit 公开 JSON 采集，不调用模型、生成报告或发送企业微信。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.reddit_bridge import RedditBridge  # noqa: E402
from utils.parser import load_articles  # noqa: E402


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reddit 公开 JSON 烟雾测试")
    parser.add_argument("query", help="一个本地过滤关键词")
    parser.add_argument(
        "--subreddit",
        default="LocalLLaMA",
        help="目标社区名称，默认 LocalLLaMA；不要包含完整 URL",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="最多输出条数，默认 3，首次测试建议保持较小",
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    query = args.query.strip()
    subreddit = args.subreddit.strip()
    if subreddit.casefold().startswith("r/"):
        subreddit = subreddit[2:]

    if not query:
        print("query 不能为空")
        return 2
    if not subreddit or subreddit.casefold() == "all":
        print("--subreddit 必须是一个明确的社区名称")
        return 2
    if args.limit <= 0 or args.limit > 20:
        print("--limit 必须在 1 到 20 之间")
        return 2

    bridge = RedditBridge()
    bridge.configured_platform = "reddit"
    bridge.keywords = [query]
    bridge.subreddits = [subreddit]
    bridge.limit = args.limit
    bridge.per_subreddit_limit = max(args.limit, 20)

    result = bridge.run()
    if not result.success:
        print(f"烟雾测试失败：{result.error}")
        return 1

    articles = load_articles(
        result.data_files,
        platform=bridge.platform,
        allow_manual_fallback=False,
    )
    if not articles:
        print("烟雾测试失败：Reddit 已返回数据，但下游解析器没有读到文章")
        return 1

    print(f"烟雾测试成功：读取并解析 {len(articles)} 条 Reddit 内容")
    for data_file in result.data_files:
        print(f"- {data_file}")
    print("本脚本不会写入已处理状态，重复测试仍可读取相同帖子。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
