import json
import os
import tempfile
import unittest

import requests
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from crawler.github_bridge import GithubBridge


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected request: {url}")
        return self.responses.pop(0)


def repository(repo_id, name, pushed_at, stars=10):
    return {
        "id": repo_id,
        "name": name.split("/")[-1],
        "full_name": name,
        "description": f"Description for {name}",
        "html_url": f"https://github.com/{name}",
        "clone_url": f"https://github.com/{name}.git",
        "owner": {"login": name.split("/")[0]},
        "pushed_at": pushed_at,
        "stargazers_count": stars,
        "forks_count": 4,
        "watchers_count": 8,
        "open_issues_count": 2,
        "language": "Python",
        "topics": ["ai", "agent"],
        "license": {"spdx_id": "MIT"},
    }


class GithubBridgeTest(unittest.TestCase):
    def make_bridge(self, temp_dir, session):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "github_pat_test"}):
            bridge = GithubBridge(
                session=session,
                now_provider=lambda: datetime(2026, 7, 24, tzinfo=timezone.utc),
            )
        root = Path(temp_dir)
        bridge.configured_platform = "github"
        bridge.keywords = ["AI Agent", "LLM"]
        bridge.limit = 3
        bridge.per_query_limit = 5
        bridge.lookback_days = 7
        bridge.min_stars = 5
        bridge.target_data_dir = root / "data"
        bridge.state_file = root / "state" / "github.json"
        return bridge

    def test_validate_requires_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("crawler.github_bridge.config.GITHUB_TOKEN", ""):
                bridge = GithubBridge(session=FakeSession([]))
        bridge.configured_platform = "github"

        self.assertIn("GITHUB_TOKEN 未配置或仍是占位值", bridge.validate())

    def test_search_deduplicates_filters_fetches_readme_and_writes_jsonl(self):
        current = repository(1, "example/agent", "2026-07-23T12:00:00Z", 20)
        old = repository(2, "example/old", "2026-07-01T12:00:00Z", 50)
        low_stars = repository(3, "example/new", "2026-07-23T11:00:00Z", 2)
        session = FakeSession(
            [
                FakeResponse(payload={"items": [current, old, low_stars]}),
                FakeResponse(payload={"items": [current]}),
                FakeResponse(text="# Agent\nREADME content"),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, session)
            result = bridge.run()
            state_exists_before_ack = bridge.state_file.exists()
            rows = [
                json.loads(line)
                for line in result.data_files[0].read_text(encoding="utf-8").splitlines()
            ]

            self.assertTrue(result.success)
            self.assertFalse(state_exists_before_ack)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], "github:1")
            self.assertEqual(rows[0]["matched_keywords"], ["AI Agent", "LLM"])
            self.assertIn("README content", rows[0]["content"])
            self.assertEqual(rows[0]["stars"], 20)

            search_call = session.calls[0]
            self.assertEqual(
                search_call[2]["headers"]["Authorization"],
                "Bearer github_pat_test",
            )
            self.assertEqual(
                search_call[2]["headers"]["X-GitHub-Api-Version"],
                "2022-11-28",
            )
            self.assertIn("pushed:>=2026-07-17", search_call[2]["params"]["q"])
            self.assertEqual(
                session.calls[-1][2]["headers"]["Accept"],
                "application/vnd.github.raw+json",
            )

            self.assertEqual(bridge.acknowledge(), "")
            state = json.loads(bridge.state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["seen_ids"], ["github:1"])

    def test_seen_repository_is_skipped_without_fetching_readme(self):
        session = FakeSession(
            [
                FakeResponse(
                    payload={
                        "items": [repository(1, "example/agent", "2026-07-23T12:00:00Z")]
                    }
                ),
                FakeResponse(payload={"items": []}),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, session)
            bridge.state_file.parent.mkdir(parents=True)
            bridge.state_file.write_text(
                json.dumps({"version": 1, "seen_ids": ["github:1"]}),
                encoding="utf-8",
            )
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("没有新的", result.error)
        self.assertEqual(len(session.calls), 2)

    def test_missing_readme_is_not_a_collection_failure(self):
        session = FakeSession(
            [
                FakeResponse(
                    payload={
                        "items": [repository(1, "example/agent", "2026-07-23T12:00:00Z")]
                    }
                ),
                FakeResponse(payload={"items": []}),
                FakeResponse(status_code=404, text="not found"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, session)
            result = bridge.run()
            row = json.loads(result.data_files[0].read_text(encoding="utf-8"))

        self.assertTrue(result.success)
        self.assertEqual(row["readme"], "")

    def test_network_failure_returns_failed_result(self):
        class FailingSession:
            def request(self, method, url, **kwargs):
                raise requests.ConnectionError("offline")

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, FailingSession())
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("网络请求失败", result.error)
        self.assertIn("ConnectionError", result.error)

    def test_rate_limit_returns_failed_result(self):
        session = FakeSession(
            [FakeResponse(status_code=403, headers={"Retry-After": "60"})]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, session)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("限流", result.error)
        self.assertIn("Retry-After=60", result.error)


if __name__ == "__main__":
    unittest.main()
