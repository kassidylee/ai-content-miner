import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from output.twitter_feed import (
    TwitterFeedRenderError,
    render_twitter_feed,
)
from utils.twitter_result_store import (
    append_twitter_results,
    load_recent_twitter_digest_items,
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

    def test_daily_html_renders_one_selected_list(self):
        items = [make_item(f"x:{index}") for index in range(1, 4)]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "reports" / "x.html"
            with patch(
                "output.twitter_feed.config.TWITTER_REPORT_FILE",
                str(output),
            ):
                render_twitter_feed(
                    items=items,
                    digest_date="2026-07-29",
                )
                page = output.read_text(encoding="utf-8")

        self.assertIn("Twitter 每日精选", page)
        self.assertIn("2026-07-29 · 精选 3 条", page)
        self.assertNotIn("更多值得关注", page)
        self.assertNotIn("查看原帖", page)

    def test_daily_html_rejects_more_than_configured_limit(self):
        items = [make_item(f"x:{index}") for index in range(1, 10)]
        with self.assertRaises(TwitterFeedRenderError):
            render_twitter_feed(items=items)

    def test_recent_digest_history_only_returns_published_items(self):
        selected = make_item("x:1")
        selected["publication_metadata"] = {
            "decision": "selected",
            "digest_date": "2026-07-23",
        }
        legacy_primary = make_item("x:3")
        legacy_primary["publication_metadata"] = {
            "decision": "primary",
            "digest_date": "2026-07-22",
        }
        archived = make_item("x:2")
        archived["publication_metadata"] = {
            "decision": "archive",
            "digest_date": "2026-07-24",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            processed_file = Path(temp_dir) / "processed" / "x.jsonl"
            with patch(
                "utils.twitter_result_store.config."
                "TWITTER_PROCESSED_FILE",
                str(processed_file),
            ):
                append_twitter_results(
                    [selected, legacy_primary, archived]
                )
                history = load_recent_twitter_digest_items(
                    now=NOW,
                    days=7,
                )

        self.assertEqual(
            {item["id"] for item in history},
            {"x:1", "x:3"},
        )


if __name__ == "__main__":
    unittest.main()
