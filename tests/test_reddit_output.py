import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from notifier.reddit_wecom import build_reddit_wecom_content
from output.reddit_feed import render_reddit_feed
from utils.reddit_result_store import (
    append_reddit_results,
    load_reddit_feed_items,
)


NOW = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)


def record(
    item_id="reddit:1",
    decision="keep",
    title="Agent runtime (open-source) - release",
    abstract="A concise technical summary.",
    published_at=NOW,
):
    return {
        "id": item_id,
        "platform_item_id": item_id.split(":")[-1],
        "platform": "reddit",
        "title": title,
        "original_title": title,
        "content": "Long source content",
        "abstract": abstract,
        "source_url": (
            "https://www.reddit.com/r/LocalLLaMA/comments/"
            f"{item_id.split(':')[-1]}/example/"
        ),
        "external_url": "https://github.com/example/project",
        "published_at": published_at,
        "author": "alice",
        "subreddit": "LocalLLaMA",
        "score": 8.0,
        "topic_label": "AI Agent",
        "filter_metadata": {
            "stages": [],
            "final_decision": decision,
            "final_reason_codes": [],
        },
        "enrichment_metadata": {
            "status": "generated",
            "error_type": "",
        },
        "processed_at": NOW,
    }


class RedditOutputTest(unittest.TestCase):
    def test_store_keeps_full_audit_but_feed_only_reads_current_kept_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            processed_file = Path(temp_dir) / "processed" / "reddit.jsonl"
            with patch(
                "utils.reddit_result_store.config.REDDIT_PROCESSED_FILE",
                str(processed_file),
            ), patch(
                "utils.reddit_result_store.config.REDDIT_FEED_RETENTION_DAYS",
                30,
            ), patch(
                "utils.reddit_result_store.config.REDDIT_FEED_MAX_ITEMS",
                20,
            ):
                append_reddit_results(
                    [
                        record("reddit:1", "keep"),
                        record("reddit:2", "drop"),
                        record(
                            "reddit:3",
                            "keep",
                            published_at=NOW - timedelta(days=31),
                        ),
                    ]
                )
                rows = [
                    json.loads(line)
                    for line in processed_file.read_text(
                        encoding="utf-8"
                    ).splitlines()
                ]
                feed = load_reddit_feed_items(now=NOW)

        self.assertEqual(len(rows), 3)
        self.assertEqual([item["id"] for item in feed], ["reddit:1"])

    def test_html_escapes_text_and_links_directly_to_reddit(self):
        item = record()
        item["title"] = "<script>alert(1)</script>"
        item["abstract"] = '<img onerror="alert(1)">'
        item["external_url"] = "javascript:alert(1)"
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "reports" / "reddit.html"
            with patch(
                "output.reddit_feed.config.REDDIT_REPORT_FILE",
                str(output),
            ):
                rendered = render_reddit_feed(items=[item])
                page = rendered.read_text(encoding="utf-8")

        self.assertEqual(rendered.name, "reddit.html")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("查看 Reddit 原帖", page)
        self.assertIn(item["source_url"], page)
        self.assertNotIn("javascript:alert(1)", page)

    def test_wecom_message_uses_plain_punctuation_and_complete_item_blocks(self):
        items = [
            record(f"reddit:{index}", abstract="技术摘要。" * 18)
            for index in range(1, 8)
        ]
        with patch(
            "notifier.reddit_wecom.config.REDDIT_WECOM_MAX_ITEMS",
            5,
        ), patch(
            "notifier.reddit_wecom.config.REDDIT_WECOM_MAX_BYTES",
            900,
        ):
            content, selected_count = build_reddit_wecom_content(items)

        self.assertLessEqual(len(content.encode("utf-8")), 900)
        self.assertGreater(selected_count, 0)
        self.assertLess(selected_count, len(items))
        self.assertEqual(
            content.count("[查看 Reddit 原帖]"),
            selected_count,
        )
        self.assertIn("本次筛选保留：7 条", content)
        self.assertIn(f"本次推送：{selected_count} 条", content)
        self.assertIn("(open-source) - release", content)
        self.assertNotIn("\\-", content)
        self.assertNotIn("REPORT_BASE_URL", content)


if __name__ == "__main__":
    unittest.main()
