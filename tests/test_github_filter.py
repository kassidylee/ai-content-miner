import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from analyzer.github_embedding import (
    GithubEmbeddingError,
    build_github_embedding_text,
    probe_github_embedding_service,
)
from analyzer.github_pipeline import run_github_filters


def item(repo_id="1", name="example/agent", **overrides):
    raw = {
        "id": repo_id,
        "full_name": name,
        "description": "An AI Agent framework",
        "readme": "README " * 150,
        "topics": ["ai", "agent"],
        "language": "Python",
        "license": "MIT",
        "stars": 1000,
        "forks": 100,
        "archived": False,
        "disabled": False,
        "fork": False,
    }
    raw.update(overrides)
    return {
        "title": name,
        "content": raw["description"] + raw["readme"],
        "source": "GitHub",
        "url": f"https://github.com/{name}",
        "publish_time": datetime(2026, 7, 23, tzinfo=timezone.utc),
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
            data=[SimpleNamespace(index=i, embedding=self.vectors[text]) for i, text in enumerate(input)]
        )


class FailingClient:
    def __init__(self):
        self.embeddings = self

    def create(self, model, input):
        error = RuntimeError("no_available_channel")
        error.status_code = 503
        raise error


class GithubFilterTest(unittest.TestCase):
    def test_pipeline_rules_embedding_and_quality(self):
        kept = item()
        low = item("2", "example/unrelated", description="Weather data")
        fork = item("3", "example/fork", fork=True)
        client = Client({
            "AI Agent": [1.0, 0.0],
            build_github_embedding_text(kept): [1.0, 0.0],
            build_github_embedding_text(low): [0.0, 1.0],
        })
        with patch("analyzer.github_embedding.config.SEARCH_KEYWORDS", ["AI Agent"]):
            result = run_github_filters(
                [kept, low, fork], client,
                datetime(2026, 7, 24, tzinfo=timezone.utc),
            )

        self.assertEqual(result["passed"], [kept])
        self.assertCountEqual(result["dropped"], [low, fork])
        self.assertEqual(kept["github_filter_metadata"]["final_decision"], "keep")
        self.assertGreaterEqual(kept["github_filter_metadata"]["stages"][-1]["score"], 5)
        self.assertEqual(low["github_filter_metadata"]["final_reason_codes"], ["GITHUB_EMBEDDING_BELOW_THRESHOLD"])
        self.assertEqual(fork["github_filter_metadata"]["final_reason_codes"], ["GITHUB_RULE_FORK_NOT_ALLOWED"])
        self.assertEqual(len(client.calls), 2)

    def test_probe_reports_provider_status_and_reason(self):
        with self.assertRaises(GithubEmbeddingError) as context:
            probe_github_embedding_service(FailingClient())

        message = str(context.exception)
        self.assertIn("HTTP 503", message)
        self.assertIn("no_available_channel", message)

    def test_embedding_text_excludes_metrics_and_owner(self):
        repository = item(stars=999999, forks=888888, owner="alice")
        text = build_github_embedding_text(repository)
        self.assertIn("仓库：example/agent", text)
        self.assertNotIn("999999", text)
        self.assertNotIn("888888", text)
        self.assertNotIn("alice", text)

    def test_archived_repository_skips_embedding(self):
        repository = item(archived=True)
        client = Client({})
        result = run_github_filters([repository], client)
        self.assertEqual(result["passed"], [])
        self.assertEqual(client.calls, [])
        self.assertEqual(repository["github_filter_metadata"]["final_reason_codes"], ["GITHUB_RULE_ARCHIVED"])


if __name__ == "__main__":
    unittest.main()
