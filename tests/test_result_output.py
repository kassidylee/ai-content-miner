import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from output.feed_renderer import render_platform_feed
from utils.result_store import (
    ResultStoreError,
    append_processed_items,
    load_feed_items,
    validate_platform_key,
)


NOW = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)


def make_item(
    item_id="x:1",
    published_at=NOW,
    decision="keep",
    title="Test title",
):
    return {
        "id": item_id,
        "platform_item_id": item_id.split(":")[-1],
        "platform": "x",
        "title": title,
        "content": "Original content",
        "abstract": "Concise abstract.",
        "source_url": f"https://x.com/user/status/{item_id.split(':')[-1]}",
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
            "final_reason_codes": ["FILTER_PIPELINE_PASSED"],
        },
        "processed_at": NOW,
        "raw": {"should_not": "persist"},
    }


class ResultStoreTest(unittest.TestCase):
    def test_atomic_append_removes_raw_and_deduplicates_current_batch(self):
        first = make_item(title="old")
        second = make_item(title="new")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = append_processed_items(
                "x",
                [first, second],
                directory=Path(temp_dir),
            )
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "new")
        self.assertNotIn("raw", rows[0])
        self.assertEqual(rows[0]["published_at"], NOW.isoformat())

    def test_latest_record_controls_visibility_and_feed_is_sorted(self):
        newer = make_item("x:2", NOW - timedelta(hours=1))
        older = make_item("x:1", NOW - timedelta(hours=2))
        expired = make_item("x:3", NOW - timedelta(days=31))
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            append_processed_items(
                "x",
                [older, newer, expired],
                directory=directory,
            )
            append_processed_items(
                "x",
                [make_item("x:2", NOW, decision="drop")],
                directory=directory,
            )
            items = load_feed_items(
                "x",
                directory=directory,
                retention_days=30,
                max_items=10,
                now=NOW,
            )

        self.assertEqual([item["id"] for item in items], ["x:1"])

    def test_max_items_is_applied_after_sorting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            append_processed_items(
                "x",
                [
                    make_item("x:1", NOW - timedelta(hours=3)),
                    make_item("x:2", NOW - timedelta(hours=1)),
                    make_item("x:3", NOW - timedelta(hours=2)),
                ],
                directory=directory,
            )
            items = load_feed_items(
                "x",
                directory=directory,
                now=NOW,
                max_items=2,
            )

        self.assertEqual([item["id"] for item in items], ["x:2", "x:3"])

    def test_invalid_platform_and_corrupt_json_are_rejected(self):
        with self.assertRaises(ResultStoreError):
            validate_platform_key("../x")

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            (directory / "x.jsonl").write_text("{bad json}\n", encoding="utf-8")
            with self.assertRaises(ResultStoreError):
                load_feed_items("x", directory=directory)


class FeedRendererTest(unittest.TestCase):
    def test_page_escapes_content_and_links_directly_to_source(self):
        item = make_item(title="<script>alert(1)</script>")
        item["abstract"] = '<img src=x onerror="alert(1)">'
        item["tags"][0]["label"] = "<AI>"
        item["referenced_urls"] = [
            {
                "url": "https://github.com/example/project?a=1&b=2",
                "label": "<Project>",
            },
            {
                "url": "javascript:alert(1)",
                "label": "unsafe",
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir)
            output = render_platform_feed(
                "x",
                items=[item],
                report_dir=report_dir,
            )
            page = output.read_text(encoding="utf-8")
            names = sorted(path.name for path in report_dir.iterdir())

        self.assertEqual(output.name, "x.html")
        self.assertEqual(names, ["x.html"])
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", page)
        self.assertIn('href="https://x.com/user/status/1"', page)
        self.assertIn("github.com/example/project?a=1&amp;b=2", page)
        self.assertNotIn("javascript:alert(1)", page)
        self.assertIn('rel="noopener noreferrer"', page)

    def test_empty_feed_still_generates_platform_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = render_platform_feed(
                "zhihu",
                items=[],
                report_dir=Path(temp_dir),
            )
            page = output.read_text(encoding="utf-8")

        self.assertEqual(output.name, "zhihu.html")
        self.assertIn("暂无符合条件的内容", page)


if __name__ == "__main__":
    unittest.main()
