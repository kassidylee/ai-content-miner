import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import config
from analyzer.reddit_common import (
    append_reddit_filter_stage,
    reddit_filter_stage,
)
from analyzer.reddit_embedding import (
    _embed_texts,
    build_reddit_embedding_text,
)
from analyzer.reddit_pipeline import (
    run_reddit_filters,
    validate_reddit_pipeline_config,
)
from analyzer.reddit_quality import (
    evaluate_reddit_quality,
    validate_reddit_quality_config,
)
from analyzer.reddit_rules import apply_reddit_rules


TOPICS = [
    {
        "id": "agent",
        "label": "AI Agent",
        "description": "AI agents, tool calling and autonomous workflows",
        "threshold": 0.35,
    },
    {
        "id": "systems",
        "label": "模型系统",
        "description": "LLM inference, quantization and model deployment",
        "threshold": 0.35,
    },
]


def item(
    post_id="abc123",
    title="Agent runtime benchmark",
    content=None,
    source="Reddit",
    **raw_overrides,
):
    body = content or (
        "A reproducible agent architecture benchmark with implementation "
        "details, inference measurements, and methodology.\n"
        "- Includes evaluation steps\n"
        "- Includes failure analysis\n"
        "```python\nfrom agent import Runtime\n```\n"
        + "technical detail " * 60
    )
    raw = {
        "id": post_id,
        "subreddit": "LocalLLaMA",
        "search_subreddit": "LocalLLaMA",
        "collection_method": "reddit_rss",
        "external_url": "https://github.com/example/agent-runtime",
        "matched_keywords": ["agent"],
        "metrics_available": False,
        "score": None,
        "comment_count": None,
        "upvote_ratio": None,
    }
    raw.update(raw_overrides)
    return {
        "title": title,
        "content": body,
        "source": source,
        "url": (
            "https://www.reddit.com/r/LocalLLaMA/comments/"
            f"{post_id}/example/"
        ),
        "author": "alice",
        "publish_time": datetime(2026, 7, 24, 11, tzinfo=timezone.utc),
        "likes": 0,
        "comments": 0,
        "collects": 0,
        "shares": 0,
        "raw": raw,
    }


class Client:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []
        self.embeddings = self

    def create(self, model, input):
        self.calls.append(list(input))
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=self.vectors[text])
                for index, text in enumerate(input)
            ]
        )


class RedditFilterTest(unittest.TestCase):
    def test_reddit_embedding_batches_full_candidate_set_by_ten(self):
        texts = [f"candidate-{index}" for index in range(23)]
        client = Client({
            text: [float(index), 1.0]
            for index, text in enumerate(texts)
        })

        vectors = _embed_texts(client, texts)

        self.assertEqual(config.REDDIT_EMBEDDING_BATCH_SIZE, 10)
        self.assertEqual([len(call) for call in client.calls], [10, 10, 3])
        self.assertEqual(len(vectors), len(texts))

    def test_pipeline_uses_reddit_rules_embedding_and_quality(self):
        kept = item()
        unrelated = item(
            "weather1",
            "Garden irrigation report",
            content="Garden moisture and irrigation schedule. " * 20,
        )
        wrong_platform = item("wrong1", source="GitHub")
        client = Client(
            {
                TOPICS[0]["description"]: [1.0, 0.0],
                TOPICS[1]["description"]: [0.0, 1.0],
                build_reddit_embedding_text(kept): [1.0, 0.0],
                build_reddit_embedding_text(unrelated): [-1.0, 0.0],
            }
        )
        with patch(
            "analyzer.reddit_embedding.config.REDDIT_INTEREST_TOPICS",
            TOPICS,
        ):
            result = run_reddit_filters(
                [kept, unrelated, wrong_platform],
                embedding_client=client,
                now=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
            )

        self.assertEqual(result["passed"], [kept])
        self.assertCountEqual(
            result["dropped"],
            [unrelated, wrong_platform],
        )
        self.assertEqual(
            kept["reddit_filter_metadata"]["final_reason_codes"],
            ["REDDIT_FILTER_PIPELINE_PASSED"],
        )
        quality = reddit_filter_stage(kept, "quality")
        self.assertGreaterEqual(quality["score"], 6.0)
        self.assertNotIn("engagement", quality["components"])
        self.assertFalse(quality["details"]["interaction_metrics_used"])
        self.assertEqual(
            unrelated["reddit_filter_metadata"]["final_reason_codes"],
            ["REDDIT_EMBEDDING_BELOW_THRESHOLD"],
        )
        self.assertEqual(
            wrong_platform["reddit_filter_metadata"]["final_reason_codes"],
            ["REDDIT_RULE_WRONG_PLATFORM"],
        )
        self.assertEqual(len(client.calls), 2)

    def test_pipeline_sorts_by_quality_before_final_result_limit(self):
        lower = item("lower")
        higher = item("higher")
        for candidate, score in ((lower, 6.4), (higher, 8.9)):
            append_reddit_filter_stage(
                candidate,
                {
                    "stage": "quality",
                    "decision": "pass",
                    "score": score,
                    "reason_codes": ["REDDIT_QUALITY_SCORE_PASSED"],
                },
            )

        with patch(
            "analyzer.reddit_pipeline.apply_reddit_rules",
            return_value=([lower, higher], []),
        ), patch(
            "analyzer.reddit_pipeline.apply_reddit_embedding_filter",
            return_value=([lower, higher], []),
        ), patch(
            "analyzer.reddit_pipeline.apply_reddit_quality_filter",
            return_value=([lower, higher], []),
        ), patch(
            "analyzer.reddit_pipeline.config.REDDIT_FINAL_RESULT_LIMIT",
            1,
        ):
            result = run_reddit_filters([lower, higher])

        self.assertEqual(result["passed"], [higher])
        self.assertEqual(result["dropped"], [lower])
        self.assertEqual(
            reddit_filter_stage(higher, "ranking")["details"]["rank"],
            1,
        )
        self.assertEqual(
            higher["reddit_filter_metadata"]["final_reason_codes"],
            ["REDDIT_FILTER_PIPELINE_PASSED"],
        )
        self.assertEqual(
            lower["reddit_filter_metadata"]["final_reason_codes"],
            ["REDDIT_FINAL_RESULT_LIMIT_EXCEEDED"],
        )

    def test_final_result_limit_must_be_positive_integer(self):
        with patch(
            "analyzer.reddit_pipeline.config.REDDIT_FINAL_RESULT_LIMIT",
            0,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "REDDIT_FINAL_RESULT_LIMIT 必须是正整数",
            ):
                validate_reddit_pipeline_config()

    def test_quality_score_ignores_unavailable_interaction_metrics(self):
        no_metrics = item()
        populated_metrics = item(
            "metrics2",
            metrics_available=True,
            score=10000,
            comment_count=500,
            upvote_ratio=0.99,
        )
        for candidate in (no_metrics, populated_metrics):
            append_reddit_filter_stage(
                candidate,
                {
                    "stage": "embedding",
                    "decision": "pass",
                    "best_topic": "agent",
                    "best_topic_label": "AI Agent",
                    "best_score": 0.9,
                    "reason_codes": [
                        "REDDIT_EMBEDDING_THRESHOLD_PASSED"
                    ],
                },
            )

        now = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
        first = evaluate_reddit_quality(no_metrics, now=now)
        second = evaluate_reddit_quality(populated_metrics, now=now)

        self.assertEqual(first["score"], second["score"])
        self.assertFalse(first["details"]["metrics_available"])
        self.assertTrue(second["details"]["metrics_available"])
        self.assertFalse(first["details"]["interaction_metrics_used"])
        self.assertFalse(second["details"]["interaction_metrics_used"])

    def test_quality_score_does_not_use_collection_keyword_match(self):
        matched = item("matched")
        unmatched = item("unmatched", matched_keywords=[])
        for candidate in (matched, unmatched):
            append_reddit_filter_stage(
                candidate,
                {
                    "stage": "embedding",
                    "decision": "pass",
                    "best_topic": "agent",
                    "best_topic_label": "AI Agent",
                    "best_score": 0.9,
                    "reason_codes": [
                        "REDDIT_EMBEDDING_THRESHOLD_PASSED"
                    ],
                },
            )

        now = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
        matched_quality = evaluate_reddit_quality(matched, now=now)
        unmatched_quality = evaluate_reddit_quality(unmatched, now=now)

        self.assertEqual(
            matched_quality["score"],
            unmatched_quality["score"],
        )
        self.assertTrue(
            matched_quality["details"]["source"]["has_collection_match"]
        )
        self.assertFalse(
            unmatched_quality["details"]["source"]["has_collection_match"]
        )
        self.assertFalse(
            matched_quality["details"]["source"][
                "collection_match_used_in_score"
            ]
        )

    def test_rules_drop_duplicate_post_id_before_embedding(self):
        first = item()
        duplicate = item()
        duplicate["url"] = (
            "https://www.reddit.com/r/LocalLLaMA/comments/"
            "abc123/a-different-slug/"
        )

        passed, dropped = apply_reddit_rules([first, duplicate])

        self.assertEqual(passed, [first])
        self.assertEqual(dropped, [duplicate])
        self.assertEqual(
            duplicate["reddit_filter_metadata"]["final_reason_codes"],
            ["REDDIT_RULE_DUPLICATE_ID"],
        )

    def test_quality_weights_must_sum_to_one(self):
        invalid = {
            "relevance": 0.35,
            "depth": 0.25,
            "evidence": 0.20,
            "freshness": 0.10,
            "source_quality": 0.20,
        }
        with patch(
            "analyzer.reddit_quality.config.REDDIT_QUALITY_WEIGHTS",
            invalid,
        ):
            with self.assertRaisesRegex(ValueError, "权重之和必须为 1"):
                validate_reddit_quality_config()


if __name__ == "__main__":
    unittest.main()
