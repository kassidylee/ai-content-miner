import unittest
from unittest.mock import patch

from analyzer.comment_filter import apply_comment_filters
from analyzer.pipeline import run_filter_pipeline
from crawler.base import CommentFetchResult


def make_item(item_id="x:1"):
    return {
        "id": item_id,
        "platform_item_id": item_id.split(":")[-1],
        "platform": "x",
        "username": "author",
        "content": "A new reasoning model",
        "filter_metadata": {
            "stages": [],
            "final_decision": "pending",
            "final_reason_codes": [],
        },
    }


def make_comment(
    comment_id,
    content,
    username,
    likes=0,
    is_original_author=False,
):
    return {
        "id": str(comment_id),
        "content": content,
        "author_username": username,
        "like_count": likes,
        "is_original_author": is_original_author,
    }


class FakeProvider:
    def __init__(self, results=None, error=None):
        self.results = results or {}
        self.error = error
        self.calls = []

    def fetch_comments(self, items, limit, timeout_seconds):
        self.calls.append((list(items), limit, timeout_seconds))
        if self.error:
            raise self.error
        return self.results


class CommentFilterTest(unittest.TestCase):
    def test_no_replies_keeps_item(self):
        item = make_item()
        provider = FakeProvider(
            {
                item["id"]: CommentFetchResult(
                    available=True,
                    comments=(),
                )
            }
        )

        passed, dropped = apply_comment_filters([item], provider)

        self.assertEqual(passed, [item])
        self.assertEqual(dropped, [])
        stage = item["filter_metadata"]["stages"][-1]
        self.assertEqual(stage["reason_codes"], ["REPLIES_EMPTY"])

    def test_low_sample_keeps_item_even_when_every_reply_is_critical(self):
        item = make_item()
        comments = tuple(
            make_comment(index, "This is fake", f"user{index}", likes=20)
            for index in range(4)
        )
        provider = FakeProvider(
            {
                item["id"]: CommentFetchResult(
                    available=True,
                    comments=comments,
                )
            }
        )

        passed, dropped = apply_comment_filters([item], provider)

        self.assertEqual(passed, [item])
        self.assertEqual(dropped, [])
        stage = item["filter_metadata"]["stages"][-1]
        self.assertEqual(stage["reason_codes"], ["REPLIES_LOW_SAMPLE"])
        self.assertEqual(stage["details"]["confidence"], "low")

    def test_small_critical_ratio_does_not_drop_item(self):
        item = make_item()
        comments = (
            make_comment(1, "This is incorrect", "critic", likes=1),
            make_comment(2, "Useful benchmark", "reader2", likes=10),
            make_comment(3, "Thanks for sharing", "reader3", likes=8),
            make_comment(4, "Interesting result", "reader4", likes=7),
            make_comment(5, "I reproduced this", "reader5", likes=6),
        )
        provider = FakeProvider(
            {
                item["id"]: CommentFetchResult(
                    available=True,
                    comments=comments,
                )
            }
        )

        passed, dropped = apply_comment_filters([item], provider)

        self.assertEqual(passed, [item])
        self.assertEqual(dropped, [])
        stage = item["filter_metadata"]["stages"][-1]
        self.assertEqual(stage["reason_codes"], ["REPLIES_PASSED"])
        self.assertEqual(stage["details"]["critical_ratio"], 0.2)

    def test_distinct_high_weight_challenges_drop_item(self):
        item = make_item()
        comments = (
            make_comment(1, "This is fabricated", "critic1", likes=50),
            make_comment(2, "No evidence for this", "critic2", likes=40),
            make_comment(3, "The result is incorrect", "critic3", likes=30),
            make_comment(4, "I agree", "reader4", likes=1),
            make_comment(5, "Interesting", "reader5", likes=1),
        )
        provider = FakeProvider(
            {
                item["id"]: CommentFetchResult(
                    available=True,
                    comments=comments,
                )
            }
        )

        passed, dropped = apply_comment_filters([item], provider)

        self.assertEqual(passed, [])
        self.assertEqual(dropped, [item])
        stage = item["filter_metadata"]["stages"][-1]
        self.assertEqual(
            stage["reason_codes"], ["REPLIES_STRONG_CHALLENGE"]
        )
        self.assertEqual(stage["details"]["critical_author_count"], 3)
        self.assertEqual(item["filter_metadata"]["final_decision"], "drop")

    def test_author_and_duplicate_account_do_not_amplify_challenge(self):
        item = make_item()
        comments = (
            make_comment(1, "This is fake", "author", likes=50, is_original_author=True),
            make_comment(2, "This is fake claim one", "critic", likes=40),
            make_comment(3, "This is fake claim two", "critic", likes=30),
            make_comment(4, "Useful", "reader1", likes=1),
            make_comment(5, "Thanks", "reader2", likes=1),
            make_comment(6, "Interesting", "reader3", likes=1),
            make_comment(7, "Good data", "reader4", likes=1),
        )
        provider = FakeProvider(
            {
                item["id"]: CommentFetchResult(
                    available=True,
                    comments=comments,
                )
            }
        )

        passed, dropped = apply_comment_filters([item], provider)

        self.assertEqual(passed, [item])
        self.assertEqual(dropped, [])
        stage = item["filter_metadata"]["stages"][-1]
        self.assertEqual(stage["details"]["critical_author_count"], 1)

    def test_one_unavailable_item_does_not_affect_other_items(self):
        first = make_item("x:1")
        second = make_item("x:2")
        provider = FakeProvider(
            {
                first["id"]: CommentFetchResult(
                    available=False,
                    error="timeout",
                ),
                second["id"]: CommentFetchResult(
                    available=True,
                    comments=(),
                ),
            }
        )

        passed, dropped = apply_comment_filters([first, second], provider)

        self.assertEqual(passed, [first, second])
        self.assertEqual(dropped, [])
        self.assertEqual(
            first["filter_metadata"]["stages"][-1]["reason_codes"],
            ["REPLIES_UNAVAILABLE"],
        )
        self.assertEqual(
            second["filter_metadata"]["stages"][-1]["reason_codes"],
            ["REPLIES_EMPTY"],
        )

    def test_provider_failure_is_recorded_as_unavailable(self):
        item = make_item()
        provider = FakeProvider(error=RuntimeError("network"))

        passed, dropped = apply_comment_filters([item], provider)

        self.assertEqual(passed, [item])
        self.assertEqual(dropped, [])
        self.assertEqual(
            item["filter_metadata"]["stages"][-1]["reason_codes"],
            ["REPLIES_UNAVAILABLE"],
        )

    def test_platform_without_comment_support_skips_provider(self):
        item = make_item()
        item["platform"] = "zhihu"
        provider = FakeProvider()

        passed, dropped = apply_comment_filters([item], provider)

        self.assertEqual(passed, [item])
        self.assertEqual(dropped, [])
        self.assertEqual(provider.calls, [])
        self.assertEqual(
            item["filter_metadata"]["stages"][-1]["reason_codes"],
            ["COMMENTS_DISABLED"],
        )

    def test_embedding_dropped_items_do_not_request_comments(self):
        item = make_item()
        provider = FakeProvider()
        initial = {
            "all_items": [item],
            "passed": [],
            "dropped": [item],
        }

        with patch(
            "analyzer.pipeline.run_initial_filters",
            return_value=initial,
        ):
            result = run_filter_pipeline(
                [item],
                comment_provider=provider,
            )

        self.assertEqual(result["passed"], [])
        self.assertEqual(result["dropped"], [item])
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
