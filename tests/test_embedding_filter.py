import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from analyzer.embedding_filter import (
    EmbeddingFilterError,
    apply_embedding_filters,
    build_embedding_text,
    cosine_similarity,
)
from analyzer.pipeline import run_initial_filters


class FakeEmbeddings:
    def __init__(self, vectors, reverse=False, error=None):
        self.vectors = vectors
        self.reverse = reverse
        self.error = error
        self.calls = []

    def create(self, model, input):
        self.calls.append((model, list(input)))
        if self.error:
            raise self.error
        data = [
            SimpleNamespace(index=index, embedding=self.vectors[text])
            for index, text in enumerate(input)
        ]
        if self.reverse:
            data.reverse()
        return SimpleNamespace(data=data)


class FakeClient:
    def __init__(self, vectors, reverse=False, error=None):
        self.embeddings = FakeEmbeddings(vectors, reverse=reverse, error=error)


def make_item(content="Agent framework"):
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


def make_topic(
    topic_id="agent",
    description="agent topic",
    threshold=0.5,
):
    return {
        "id": topic_id,
        "label": topic_id,
        "description": description,
        "threshold": threshold,
        "tag_id": topic_id,
    }


class EmbeddingFilterTest(unittest.TestCase):
    def test_build_text_combines_content_quote_links_and_hashtags(self):
        item = make_item("发布新的智能体框架")
        item["quoted_content"] = "工具调用基准"
        item["username"] = "alice"
        item["metrics"] = {"like_count": 99, "view_count": 1000}
        item["referenced_urls"] = [
            {
                "url": "https://github.com/example/project",
                "label": "example/project",
                "domain": "github.com",
            }
        ]
        item["platform_metadata"]["hashtags"] = ["AI", "AI", "Agent"]

        text = build_embedding_text(item)

        self.assertIn("发布新的智能体框架", text)
        self.assertIn("工具调用基准", text)
        self.assertIn("example/project", text)
        self.assertIn("AI, Agent", text)
        self.assertNotIn("alice", text)
        self.assertNotIn("1000", text)
        self.assertEqual(item["content"], "发布新的智能体框架")

    def test_build_text_respects_length_limit(self):
        item = make_item("a" * 100)

        text = build_embedding_text(item, max_chars=20)

        self.assertEqual(len(text), 20)

    def test_cosine_similarity_and_zero_vector(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [1, 1]), 1 / math.sqrt(2))
        self.assertEqual(cosine_similarity([0, 0], [1, 1]), 0.0)

    def test_cosine_rejects_mismatched_dimensions(self):
        with self.assertRaises(EmbeddingFilterError):
            cosine_similarity([1], [1, 2])

    def test_each_topic_uses_its_own_threshold(self):
        item = make_item()
        text = build_embedding_text(item)
        topics = [
            make_topic("strict", "strict topic", 0.95),
            make_topic("broad", "broad topic", 0.70),
        ]
        client = FakeClient(
            {
                "strict topic": [0.9, math.sqrt(1 - 0.9**2)],
                "broad topic": [0.8, 0.6],
                text: [1.0, 0.0],
            }
        )

        passed, dropped = apply_embedding_filters(
            [item], client=client, topics=topics, mode="enforce"
        )

        self.assertEqual(passed, [item])
        self.assertEqual(dropped, [])
        metadata = item["filter_metadata"]["stages"][-1]
        self.assertEqual(metadata["best_topic"], "strict")
        self.assertEqual(metadata["matched_topics"], ["broad"])

    def test_shadow_keeps_low_score_and_enforce_drops_it(self):
        topic = make_topic(threshold=0.9)
        shadow_item = make_item()
        enforce_item = make_item()
        text = build_embedding_text(shadow_item)
        vectors = {"agent topic": [0, 1], text: [1, 0]}

        shadow_passed, shadow_dropped = apply_embedding_filters(
            [shadow_item],
            client=FakeClient(vectors),
            topics=[topic],
            mode="shadow",
        )
        enforce_passed, enforce_dropped = apply_embedding_filters(
            [enforce_item],
            client=FakeClient(vectors),
            topics=[topic],
            mode="enforce",
        )

        self.assertEqual(shadow_passed, [shadow_item])
        self.assertEqual(shadow_dropped, [])
        self.assertEqual(
            shadow_item["filter_metadata"]["stages"][-1]["decision"],
            "shadow_drop",
        )
        self.assertEqual(enforce_passed, [])
        self.assertEqual(enforce_dropped, [enforce_item])
        self.assertEqual(
            enforce_item["filter_metadata"]["final_decision"], "drop"
        )

    def test_empty_text_does_not_call_api(self):
        item = make_item("")
        client = FakeClient({})

        passed, dropped = apply_embedding_filters(
            [item],
            client=client,
            topics=[make_topic()],
            mode="enforce",
        )

        self.assertEqual(passed, [])
        self.assertEqual(dropped, [item])
        self.assertEqual(client.embeddings.calls, [])
        self.assertEqual(
            item["filter_metadata"]["final_reason_codes"],
            ["EMBEDDING_EMPTY_TEXT"],
        )

    def test_batching_and_response_indexes_restore_order(self):
        items = [make_item(f"item-{index}") for index in range(3)]
        texts = [build_embedding_text(item) for item in items]
        vectors = {
            "agent topic": [1, 0],
            texts[0]: [1, 0],
            texts[1]: [0.9, 0.1],
            texts[2]: [0.8, 0.2],
        }
        client = FakeClient(vectors, reverse=True)

        passed, dropped = apply_embedding_filters(
            items,
            client=client,
            topics=[make_topic(threshold=0.5)],
            mode="enforce",
            batch_size=2,
        )

        self.assertEqual(passed, items)
        self.assertEqual(dropped, [])
        self.assertEqual(len(client.embeddings.calls), 3)
        self.assertEqual(client.embeddings.calls[0][1], ["agent topic"])
        self.assertEqual(client.embeddings.calls[1][1], texts[:2])
        self.assertEqual(client.embeddings.calls[2][1], texts[2:])

    def test_api_failure_hides_sensitive_details(self):
        item = make_item()
        client = FakeClient({}, error=RuntimeError("secret-key"))

        with self.assertRaises(EmbeddingFilterError) as context:
            apply_embedding_filters(
                [item],
                client=client,
                topics=[make_topic()],
            )

        self.assertNotIn("secret-key", str(context.exception))

    def test_initial_pipeline_skips_api_when_rules_drop_everything(self):
        item = make_item("")
        client = FakeClient({})
        rules = {
            "default": {"min_meaningful_chars": 1},
            "x": {
                "require_platform_id": True,
                "min_meaningful_chars": 20,
                "allowed_languages": ["en"],
            },
        }

        with patch("analyzer.filter.config.PLATFORM_FILTERS", rules):
            result = run_initial_filters([item], embedding_client=client)

        self.assertEqual(result["passed"], [])
        self.assertEqual(client.embeddings.calls, [])


if __name__ == "__main__":
    unittest.main()
