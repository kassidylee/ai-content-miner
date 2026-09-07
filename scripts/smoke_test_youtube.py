"""Map an existing YTB_LLM digest into YouTube structured records."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from output.youtube_feed import (  # noqa: E402
    validate_youtube_record,
    youtube_records_from_digest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube digest mapping smoke test")
    parser.add_argument(
        "--date",
        default="2026-07-26",
        help="Existing YTB_LLM digest date to read, default 2026-07-26",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Sample records to print, default 3",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.limit <= 0 or args.limit > 10:
        print("--limit must be between 1 and 10")
        return 2
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print("--date must use YYYY-MM-DD")
        return 2

    digest_path = (
        Path(config.YOUTUBE_YTB_LLM_PATH)
        / "data"
        / "digests"
        / f"digest_{args.date}.json"
    )
    if not digest_path.exists():
        print(f"Missing YTB_LLM digest: {digest_path}")
        return 3

    try:
        digest = json.loads(digest_path.read_text(encoding="utf-8"))
        records = youtube_records_from_digest(
            digest,
            processed_at=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
        )
        for record in records:
            validate_youtube_record(record)
    except Exception as exc:
        print(f"YouTube smoke test failed: {type(exc).__name__}: {exc}")
        return 1

    print(f"YouTube smoke test produced {len(records)} feed records")
    print("Validation: passed")
    for record in records[: args.limit]:
        sample = {
            "id": record["id"],
            "platform": record["platform"],
            "title": record["title"],
            "source_url": record["source_url"],
            "published_at": record["published_at"],
            "author": record["author"],
            "score": record["score"],
            "topic_label": record["topic_label"],
            "metrics": record["metrics"],
            "filter_metadata": record["filter_metadata"],
            "enrichment_metadata": record["enrichment_metadata"],
            "platform_metadata": record["platform_metadata"],
        }
        print(json.dumps(sample, ensure_ascii=False, indent=2, default=str))
    print("No processed state was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
