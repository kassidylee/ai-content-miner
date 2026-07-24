import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from output.twitter_feed import render_twitter_feed
from utils.twitter_result_store import (
    append_twitter_results,
    load_twitter_feed_items,
)


NOW = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)


def make_item(item_id="x:1", decision="keep", published_at=NOW):
    return {
        "id": item_id,
        "platform_item_id": item_id.split(":")[-1],
        "platform": "x",
        "title": "Twitter title",
        "content": "Twitter content",
        "abstract": "Concise abstract.",
        "source_url": (
            f"https://x.com/user/status/{item_id.split(':')[-1]}"
        ),
        "referenced_urls": [],
        "published_at": published_at,
        "author": "Alice",
        "username": "alice",
        "metrics": {
            "like_count": 10,
            "reply_count": 2,
            "share_count": 3,
            "view_count": 100,
        },
        "tags": [
            {
                "id": "ai",
                "label": "AI",
                "level": 1,
                "parent_id": None,
                "source": "taxonomy",
            }
        ],
        "filter_metadata": {
            "stages": [],
            "final_decision": decision,
            "final_reason_codes": [],
        },
        "processed_at": NOW,
    }


class TwitterOutputTest(unittest.TestCase):
    def test_store_contains_keep_and_drop_but_feed_only_reads_keep(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            processed_file = Path(temp_dir) / "processed" / "x.jsonl"
            with patch(
                "utils.twitter_result_store.config."
                "TWITTER_PROCESSED_FILE",
                str(processed_file),
            ), patch(
                "utils.twitter_result_store.config."
                "TWITTER_FEED_RETENTION_DAYS",
                30,
            ), patch(
                "utils.twitter_result_store.config."
                "TWITTER_FEED_MAX_ITEMS",
                20,
            ):
                append_twitter_results(
                    [
                        make_item("x:1", "keep"),
                        make_item("x:2", "drop"),
                        make_item(
                            "x:3",
                            "keep",
                            NOW - timedelta(days=31),
                        ),
                    ]
                )
                rows = [
                    json.loads(line)
                    for line in processed_file.read_text(
                        encoding="utf-8"
                    ).splitlines()
                ]
                feed = load_twitter_feed_items(now=NOW)

        self.assertEqual(len(rows), 3)
        self.assertEqual([item["id"] for item in feed], ["x:1"])

    def test_html_escapes_text_and_links_to_original_tweet(self):
        item = make_item()
        item["title"] = "<script>alert(1)</script>"
        item["abstract"] = '<img onerror="alert(1)">'
        item["referenced_urls"] = [
            {
                "url": "javascript:alert(1)",
                "label": "unsafe",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "reports" / "x.html"
            with patch(
                "output.twitter_feed.config.TWITTER_REPORT_FILE",
                str(output),
            ):
                rendered = render_twitter_feed(items=[item])
                page = rendered.read_text(encoding="utf-8")

        self.assertEqual(rendered.name, "x.html")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn('href="https://x.com/user/status/1"', page)
        self.assertNotIn("javascript:alert(1)", page)
        self.assertIn('rel="noopener noreferrer"', page)


if __name__ == "__main__":
    unittest.main()
