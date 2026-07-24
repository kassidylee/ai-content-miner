"""Run a read-only GitHub repository search without downstream processing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from crawler.github_bridge import GithubBridge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitHub 仓库搜索烟雾测试")
    parser.add_argument("keywords", nargs="+", help="一个或多个仓库搜索关键词")
    parser.add_argument("--limit", type=int, default=3, help="最多输出仓库数")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.limit <= 0 or args.limit > 10:
        print("--limit 必须在 1 到 10 之间")
        return 2

    config.CRAWL_PLATFORM = "github"
    config.SEARCH_KEYWORDS = args.keywords
    config.CRAWL_LIMIT = args.limit
    config.GITHUB_RESULTS_PER_QUERY = args.limit

    bridge = GithubBridge()
    errors = bridge.validate()
    if errors:
        for error in errors:
            print(f"配置错误: {error}")
        return 2

    result = bridge.run()
    if not result.success:
        print(result.error)
        return 3

    rows = [
        json.loads(line)
        for line in result.data_files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"成功获取 {len(rows)} 个仓库；未写入已处理状态")
    for row in rows:
        print(
            f"- {row['title']} | stars={row['stars']} | "
            f"{row['url']}"
        )
    print(f"JSONL: {result.data_files[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
