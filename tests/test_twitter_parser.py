import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.twitter_parser import load_twitter_items, normalize_twitter_item


class TwitterParserTest(unittest.TestCase):
    def test_normalizes_twscrape_fields_without_using_legacy_parser(self):
        item = normalize_twitter_item(
            {
                "id": "123",
                "title": "first line",
                "content": "A new agent framework",
                "quoted_content": "quoted benchmark",
                "url": "https://x.com/alice/status/123",
                "author": "Alice",
                "username": "alice",
                "publish_time": "2026-07-22T08:30:00+00:00",
                "like_count": 12,
                "comment_count": 3,
                "referenced_urls": [
                    {
                        "url": "https://github.com/example/project",
                        "label": "example/project",
                    }
                ],
                "matched_keywords": ["AI", "LLM"],
                "platform_metadata": {
                    "lang": "en",
                    "hashtags": ["AI"],
                    "is_reply": False,
                },
            }
        )

        self.assertEqual(item["id"], "x:123")
        self.assertEqual(item["platform"], "x")
        self.assertEqual(
            item["source_url"],
            "https://x.com/alice/status/123",
        )
        self.assertEqual(item["quoted_content"], "quoted benchmark")
        self.assertEqual(
            item["referenced_urls"][0]["domain"],
            "github.com",
        )
        self.assertEqual(item["metrics"]["like_count"], 12)
        self.assertEqual(
            item["platform_metadata"]["matched_keywords"],
            ["AI", "LLM"],
        )
        self.assertEqual(
            item["filter_metadata"]["final_decision"],
            "pending",
        )

    def test_loader_only_reads_explicit_twitter_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            content_file = root / "search_contents_2026-07-22.jsonl"
            comment_file = root / "search_comments_2026-07-22.jsonl"
            row = {
                "id": "1",
                "content": "content",
                "url": "https://x.com/alice/status/1",
                "publish_time": "2026-07-22T08:30:00+00:00",
            }
            content_file.write_text(
                json.dumps(row) + "\n",
                encoding="utf-8",
            )
            comment_file.write_text(
                json.dumps({"id": "comment"}) + "\n",
                encoding="utf-8",
            )
            with patch(
                "utils.twitter_parser.config.CRAWL_LIMIT",
                20,
            ):
                items = load_twitter_items(
                    [content_file, comment_file]
                )

        self.assertEqual([item["id"] for item in items], ["x:1"])


if __name__ == "__main__":
    unittest.main()
