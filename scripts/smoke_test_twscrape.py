"""只测试 twscrape 搜索，不调用模型、写结构化结果或发送通知。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.twscrape_bridge import TwscrapeBridge  # noqa: E402


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="twscrape 只读搜索烟雾测试")
    parser.add_argument("query", help="一个 X 搜索关键词或查询表达式")
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="最多读取条数，默认 3，建议首次测试保持较小",
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    if args.limit <= 0 or args.limit > 20:
        print("--limit 必须在 1 到 20 之间")
        return 2

    bridge = TwscrapeBridge()
    bridge.configured_platform = "x"
    bridge.keywords = [args.query.strip()]
    bridge.limit = args.limit
    bridge.per_query_limit = args.limit
    if not bridge.keywords[0]:
        print("query 不能为空")
        return 2

    result = bridge.run()
    if not result.success:
        print(f"烟雾测试失败：{result.error}")
        return 1

    row_count = 0
    for data_file in result.data_files:
        with data_file.open("r", encoding="utf-8") as file_obj:
            row_count += sum(1 for line in file_obj if line.strip())
    print(f"烟雾测试成功：读取 {row_count} 条 X 内容")
    for data_file in result.data_files:
        print(f"- {data_file}")
    print("本脚本不会写入已处理状态，重复测试仍可读取相同帖子。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
