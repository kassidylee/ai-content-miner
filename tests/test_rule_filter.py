import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from analyzer.filter import apply_rule_filters, build_meaningful_text


def make_item(content="一条包含足够技术信息的 Twitter 推文"):
    return {
        "id": "x:1",
        "platform_item_id": "1",
        "platform": "x",
        "title": content[:40],
        "content": content,
        "source_url": "https://x.com/alice/status/1",
        "referenced_urls": [],
        "published_at": datetime(2026, 7, 24, tzinfo=timezone.utc),
        "platform_metadata": {
            "lang": "zh",
            "is_reply": False,
            "is_retweet": False,
            "is_quote": False,
            "possibly_sensitive": False,
        },
        "filter_metadata": {
            "stages": [],
            "final_decision": "pending",
            "final_reason_codes": [],
        },
    }


class RuleFilterTest(unittest.TestCase):
    def setUp(self):
        self.rules = {
            "default": {
                "allowed_languages": [],
                "allow_replies": True,
                "allow_retweets": True,
                "allow_quotes": True,
                "drop_sensitive": False,
                "min_meaningful_chars": 1,
                "require_platform_id": False,
                "exclude_keywords": [],
            },
            "x": {
                "allowed_languages": ["zh", "en"],
                "allow_replies": False,
                "allow_retweets": False,
                "allow_quotes": True,
                "drop_sensitive": True,
                "min_meaningful_chars": 20,
                "require_platform_id": True,
                "exclude_keywords": ["airdrop", "空投"],
            },
        }

    def apply(self, items):
        with patch("analyzer.filter.config.PLATFORM_FILTERS", self.rules):
            return apply_rule_filters(items)

    def test_short_text_with_external_link_is_kept(self):
        item = make_item("开源")
        item["referenced_urls"] = [
            {"url": "https://github.com/example/project", "domain": "github.com"}
        ]

        passed, dropped = self.apply([item])

        self.assertEqual(passed, [item])
        self.assertEqual(dropped, [])

    def test_reply_and_retweet_are_configurable(self):
        reply = make_item()
        reply["platform_metadata"]["is_reply"] = True
        retweet = make_item("另一条包含足够技术信息的 Twitter 推文")
        retweet["id"] = "x:2"
        retweet["platform_item_id"] = "2"
        retweet["source_url"] = "https://x.com/alice/status/2"
        retweet["platform_metadata"]["is_retweet"] = True

        passed, dropped = self.apply([reply, retweet])

        self.assertEqual(passed, [])
        self.assertEqual(
            dropped[0]["filter_metadata"]["final_reason_codes"],
            ["RULE_REPLY_NOT_ALLOWED"],
        )
        self.assertEqual(
            dropped[1]["filter_metadata"]["final_reason_codes"],
            ["RULE_RETWEET_NOT_ALLOWED"],
        )

    def test_duplicate_content_is_recorded(self):
        first = make_item()
        second = make_item()
        second["id"] = "x:2"
        second["platform_item_id"] = "2"
        second["source_url"] = "https://x.com/alice/status/2"

        passed, dropped = self.apply([first, second])

        self.assertEqual(passed, [first])
        self.assertEqual(
            dropped[0]["filter_metadata"]["final_reason_codes"],
            ["RULE_DUPLICATE_CONTENT"],
        )

    def test_excluded_keyword_is_recorded(self):
        item = make_item("AI airdrop 活动现在开始领取")

        passed, dropped = self.apply([item])

        self.assertEqual(passed, [])
        self.assertEqual(
            dropped[0]["filter_metadata"]["final_reason_codes"],
            ["RULE_EXCLUDED_KEYWORD"],
        )

    def test_meaningful_text_removes_links_and_mentions(self):
        item = make_item("@alice 发布 https://example.com ## AI Agent")

        text = build_meaningful_text(item)

        self.assertNotIn("@alice", text)
        self.assertNotIn("https", text)
        self.assertIn("AI", text)


if __name__ == "__main__":
    unittest.main()
