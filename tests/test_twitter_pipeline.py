import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from analyzer.twitter_comments import apply_twitter_comment_filter
from analyzer.twitter_embedding import (
    TwitterEmbeddingError,
    apply_twitter_embedding_filter,
    build_twitter_embedding_text,
    cosine_similarity,
)
from analyzer.twitter_pipeline import run_twitter_filters
from analyzer.twitter_rules import apply_twitter_rules


def make_item(content="A new AI Agent framework with tool calling"):
    return {
        "id": "x:1",
        "platform_item_id": "1",
        "platform": "x",
        "title": content,
        "content": content,
        "quoted_content": "",
        "source_url": "https://x.com/alice/status/1",
        "referenced_urls": [],
        "published_at": object(),
        "author": "Alice",
        "username": "alice",
        "metrics": {},
        "platform_metadata": {
            "lang": "en",
            "hashtags": [],
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


class FakeEmbeddings:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def create(self, model, input):
        self.calls.append((model, list(input)))
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    index=index,
                    embedding=self.vectors[text],
                )
                for index, text in enumerate(input)
            ]
        )


class FakeEmbeddingClient:
    def __init__(self, vectors):
        self.embeddings = FakeEmbeddings(vectors)


class FakeReplyProvider:
    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    def fetch_replies(self, items, limit, timeout_seconds):
        self.calls.append((list(items), limit, timeout_seconds))
        return self.results


class TwitterPipelineTest(unittest.TestCase):
    def test_embedding_text_uses_content_quote_links_and_hashtags_only(self):
        item = make_item("  Agent   framework  ")
        item["quoted_content"] = "Quoted benchmark"
        item["referenced_urls"] = [
            {
                "url": "https://github.com/example/project",
                "label": "github.com/example/project",
                "domain": "github.com",
            }
        ]
        item["platform_metadata"]["hashtags"] = ["AI", "AI", "x"]
        item["metrics"] = {
            "like_count": 999,
            "reply_count": 888,
            "view_count": 777,
        }
        original_content = item["content"]

        text = build_twitter_embedding_text(item)

        self.assertIn("Agent framework", text)
        self.assertIn("Quoted benchmark", text)
        self.assertIn("github.com/example/project", text)
        self.assertIn("主题词：AI", text)
        self.assertNotIn("999", text)
        self.assertNotIn("888", text)
        self.assertNotIn("alice", text)
        self.assertEqual(item["content"], original_content)

    def test_embedding_text_respects_configured_length(self):
        item = make_item("a" * 100)
        with patch(
            "analyzer.twitter_embedding.config."
            "TWITTER_EMBEDDING_MAX_CHARS",
            12,
        ):
            text = build_twitter_embedding_text(item)

        self.assertEqual(len(text), 12)

    def test_cosine_handles_zero_and_dimension_errors(self):
        self.assertEqual(cosine_similarity([0, 0], [1, 0]), 0.0)
        with self.assertRaises(TwitterEmbeddingError):
            cosine_similarity([1, 0], [1])

    def test_rules_only_apply_twitter_configuration(self):
        reply = make_item()
        reply["platform_metadata"]["is_reply"] = True
        project = make_item("new")
        project["id"] = "x:2"
        project["platform_item_id"] = "2"
        project["source_url"] = "https://x.com/alice/status/2"
        project["referenced_urls"] = [
            {
                "url": "https://github.com/example/project",
                "label": "example/project",
                "domain": "github.com",
            }
        ]

        passed, dropped = apply_twitter_rules([reply, project])

        self.assertEqual(passed, [project])
        self.assertEqual(dropped, [reply])
        self.assertEqual(
            reply["filter_metadata"]["final_reason_codes"],
            ["TWITTER_RULE_REPLY_NOT_ALLOWED"],
        )

    def test_embedding_uses_best_topic_own_threshold(self):
        item = make_item()
        text = build_twitter_embedding_text(item)
        topics = [
            {
                "id": "strict",
                "label": "Strict",
                "description": "strict topic",
                "threshold": 0.95,
                "tag_id": "ai-agent",
            },
            {
                "id": "broad",
                "label": "Broad",
                "description": "broad topic",
                "threshold": 0.70,
                "tag_id": "ai-agent",
            },
        ]
        client = FakeEmbeddingClient(
            {
                "strict topic": [0.9, math.sqrt(1 - 0.9**2)],
                "broad topic": [0.8, 0.6],
                text: [1.0, 0.0],
            }
        )
        with patch(
            "analyzer.twitter_embedding.config.TWITTER_INTEREST_TOPICS",
            topics,
        ), patch(
            "analyzer.twitter_embedding.config."
            "TWITTER_EMBEDDING_FILTER_MODE",
            "enforce",
        ):
            passed, dropped = apply_twitter_embedding_filter(
                [item],
                client=client,
            )

        self.assertEqual(passed, [])
        self.assertEqual(dropped, [item])
        stage = item["filter_metadata"]["stages"][-1]
        self.assertEqual(stage["best_topic"], "strict")
        self.assertEqual(stage["matched_topics"], ["broad"])
        self.assertEqual(stage["threshold"], 0.95)
        self.assertEqual(stage["decision"], "drop")
        self.assertAlmostEqual(
            cosine_similarity([1, 0], [1, 1]),
            1 / math.sqrt(2),
        )
        self.assertEqual(len(client.embeddings.calls), 2)
        self.assertEqual(
            client.embeddings.calls[0][1],
            ["strict topic", "broad topic"],
        )

    def test_embedding_shadow_mode_records_but_keeps_low_score(self):
        item = make_item()
        text = build_twitter_embedding_text(item)
        topics = [
            {
                "id": "topic",
                "label": "Topic",
                "description": "target",
                "threshold": 0.8,
                "tag_id": "ai-agent",
            }
        ]
        client = FakeEmbeddingClient(
            {
                "target": [0.0, 1.0],
                text: [1.0, 0.0],
            }
        )
        with patch(
            "analyzer.twitter_embedding.config.TWITTER_INTEREST_TOPICS",
            topics,
        ), patch(
            "analyzer.twitter_embedding.config."
            "TWITTER_EMBEDDING_FILTER_MODE",
            "shadow",
        ):
            passed, dropped = apply_twitter_embedding_filter(
                [item],
                client=client,
            )

        self.assertEqual(passed, [item])
        self.assertEqual(dropped, [])
        stage = item["filter_metadata"]["stages"][-1]
        self.assertEqual(stage["decision"], "shadow_drop")
        self.assertEqual(
            stage["reason_codes"],
            ["TWITTER_EMBEDDING_BELOW_THRESHOLD"],
        )

    def test_low_reply_sample_keeps_item(self):
        item = make_item()
        comments = [
            {
                "id": str(index),
                "content": "This is fake",
                "author_username": f"critic{index}",
                "like_count": 20,
            }
            for index in range(4)
        ]
        provider = FakeReplyProvider(
            {
                item["id"]: {
                    "available": True,
                    "comments": comments,
                    "error": "",
                }
            }
        )

        passed, dropped = apply_twitter_comment_filter([item], provider)

        self.assertEqual(passed, [item])
        self.assertEqual(dropped, [])
        self.assertEqual(
            item["filter_metadata"]["stages"][-1]["reason_codes"],
            ["TWITTER_REPLIES_LOW_SAMPLE"],
        )

    def test_strong_distinct_challenges_drop_item(self):
        item = make_item()
        comments = [
            {
                "id": "1",
                "content": "This is fabricated",
                "author_username": "critic1",
                "like_count": 50,
            },
            {
                "id": "2",
                "content": "No evidence for this",
                "author_username": "critic2",
                "like_count": 40,
            },
            {
                "id": "3",
                "content": "The result is incorrect",
                "author_username": "critic3",
                "like_count": 30,
            },
            {
                "id": "4",
                "content": "Interesting",
                "author_username": "reader4",
                "like_count": 1,
            },
            {
                "id": "5",
                "content": "Thanks",
                "author_username": "reader5",
                "like_count": 1,
            },
        ]
        provider = FakeReplyProvider(
            {
                item["id"]: {
                    "available": True,
                    "comments": comments,
                    "error": "",
                }
            }
        )

        passed, dropped = apply_twitter_comment_filter([item], provider)

        self.assertEqual(passed, [])
        self.assertEqual(dropped, [item])
        self.assertEqual(
            item["filter_metadata"]["final_reason_codes"],
            ["TWITTER_REPLIES_STRONG_CHALLENGE"],
        )

    def test_rule_drop_skips_embedding_and_replies(self):
        item = make_item("")
        embedding_client = FakeEmbeddingClient({})
        reply_provider = FakeReplyProvider()

        result = run_twitter_filters(
            [item],
            embedding_client=embedding_client,
            reply_provider=reply_provider,
        )

        self.assertEqual(result["passed"], [])
        self.assertEqual(result["dropped"], [item])
        self.assertEqual(embedding_client.embeddings.calls, [])
        self.assertEqual(reply_provider.calls, [])


if __name__ == "__main__":
    unittest.main()
