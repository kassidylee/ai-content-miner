import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from crawler.reddit_bridge import RedditBridge


class FakeSubreddit:
    def __init__(self, name, results, calls):
        self.name = name
        self.results = results
        self.calls = calls

    def search(self, query, sort, time_filter, limit):
        self.calls.append((self.name, query, sort, time_filter, limit))
        result = self.results[(self.name, query)]
        if isinstance(result, Exception):
            raise result
        return iter(result[:limit])


class FakeReddit:
    def __init__(self, results):
        self.results = results
        self.calls = []
        self.factory_kwargs = None

    def subreddit(self, name):
        return FakeSubreddit(name, self.results, self.calls)


def make_submission(post_id, title, hour, subreddit="MachineLearning", body="正文"):
    return SimpleNamespace(
        id=str(post_id),
        title=title,
        selftext=body,
        created_utc=datetime(
            2026, 7, 23, hour, tzinfo=timezone.utc
        ).timestamp(),
        author="alice",
        subreddit=subreddit,
        permalink=f"/r/{subreddit}/comments/{post_id}/example/",
        url=f"https://example.com/{post_id}",
        score=42,
        upvote_ratio=0.91,
        num_comments=7,
        is_self=bool(body),
        over_18=False,
        link_flair_text="Research",
        domain="self.MachineLearning" if body else "example.com",
    )


class RedditBridgeTest(unittest.TestCase):
    def make_bridge(self, temp_dir, reddit):
        def reddit_factory(**kwargs):
            reddit.factory_kwargs = kwargs
            return reddit

        bridge = RedditBridge(
            reddit_factory=reddit_factory,
            now_provider=lambda: datetime(
                2026, 7, 23, 12, tzinfo=timezone.utc
            ),
        )
        root = Path(temp_dir)
        bridge.configured_platform = "reddit"
        bridge.client_id = "test-client"
        bridge.client_secret = "test-secret"
        bridge.user_agent = "macos:ai-content-miner:test (by u/tester)"
        bridge.state_file = root / "state" / "seen.json"
        bridge.target_data_dir = root / "data"
        bridge.keywords = ["AI", "LLM"]
        bridge.subreddits = ["all", "LocalLLaMA"]
        bridge.limit = 3
        bridge.per_query_limit = 3
        bridge.lookback_hours = 168
        bridge.validate = lambda: []
        return bridge

    def test_validate_requires_dependency_and_read_only_credentials(self):
        bridge = RedditBridge()
        bridge.configured_platform = "reddit"
        bridge.client_id = ""
        bridge.client_secret = ""
        bridge.user_agent = ""
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            with patch(
                "crawler.reddit_bridge.importlib.util.find_spec",
                return_value=None,
            ):
                errors = bridge.validate()

        self.assertTrue(any("REDDIT_CLIENT_ID" in error for error in errors))
        self.assertTrue(any("REDDIT_CLIENT_SECRET" in error for error in errors))
        self.assertTrue(any("REDDIT_USER_AGENT" in error for error in errors))
        self.assertTrue(any("缺少 PRAW" in error for error in errors))

    def test_validate_accepts_supported_configuration(self):
        bridge = RedditBridge()
        bridge.configured_platform = "reddit"
        bridge.client_id = "client"
        bridge.client_secret = "secret"
        bridge.user_agent = "macos:ai-content-miner:0.1 (by u/tester)"
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            with (
                patch(
                    "crawler.reddit_bridge.importlib.util.find_spec",
                    return_value=object(),
                ),
                patch(
                    "crawler.reddit_bridge.metadata.version",
                    return_value="8.0.2",
                ),
            ):
                errors = bridge.validate()

        self.assertEqual(errors, [])

    def test_run_searches_scopes_deduplicates_sorts_and_preserves_metrics(self):
        post_one = make_submission("1", "newest", 11)
        post_two = make_submission("2", "older", 8)
        post_three = make_submission("3", "middle", 10, subreddit="LocalLLaMA")
        reddit = FakeReddit(
            {
                ("all", "AI"): [post_one, post_two],
                ("all", "LLM"): [post_two],
                ("LocalLLaMA", "AI"): [post_three],
                ("LocalLLaMA", "LLM"): [],
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, reddit)
            result = bridge.run()

            self.assertTrue(result.success)
            rows = [
                json.loads(line)
                for line in result.data_files[0].read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual([row["id"] for row in rows], ["1", "3", "2"])
            self.assertEqual(rows[0]["source"], "Reddit")
            self.assertEqual(
                rows[0]["url"],
                "https://www.reddit.com/r/MachineLearning/comments/1/example/",
            )
            self.assertEqual(rows[0]["external_url"], "https://example.com/1")
            self.assertEqual(rows[0]["score"], 42)
            self.assertEqual(rows[0]["upvote_ratio"], 0.91)
            self.assertEqual(rows[0]["comment_count"], 7)
            self.assertFalse(bridge.state_file.exists())
            self.assertEqual(
                reddit.calls,
                [
                    ("all", "AI", "new", "week", 3),
                    ("all", "LLM", "new", "week", 3),
                    ("LocalLLaMA", "AI", "new", "week", 3),
                    ("LocalLLaMA", "LLM", "new", "week", 3),
                ],
            )
            self.assertEqual(reddit.factory_kwargs["client_id"], "test-client")
            self.assertEqual(
                reddit.factory_kwargs["requestor_kwargs"], {"timeout": 30.0}
            )
            self.assertNotIn("username", reddit.factory_kwargs)
            self.assertNotIn("password", reddit.factory_kwargs)

            self.assertEqual(bridge.acknowledge(), "")
            state = json.loads(bridge.state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["seen_ids"], ["1", "3", "2"])

    def test_link_post_uses_title_as_content(self):
        post = make_submission("1", "link title", 11, body="")
        reddit = FakeReddit(
            {
                ("all", "AI"): [post],
                ("all", "LLM"): [],
                ("LocalLLaMA", "AI"): [],
                ("LocalLLaMA", "LLM"): [],
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, reddit)
            result = bridge.run()
            row = json.loads(
                result.data_files[0].read_text(encoding="utf-8").splitlines()[0]
            )

        self.assertEqual(row["content"], "link title")
        self.assertFalse(row["is_self"])

    def test_seen_and_old_posts_are_skipped_without_changing_state(self):
        old_post = make_submission("old", "too old", 1)
        old_post.created_utc = datetime(
            2026, 7, 1, tzinfo=timezone.utc
        ).timestamp()
        reddit = FakeReddit(
            {
                ("all", "AI"): [
                    make_submission("seen", "seen", 11),
                    old_post,
                    make_submission("new", "new", 10),
                ],
                ("all", "LLM"): [],
                ("LocalLLaMA", "AI"): [],
                ("LocalLLaMA", "LLM"): [],
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, reddit)
            bridge.state_file.parent.mkdir(parents=True)
            bridge.state_file.write_text(
                json.dumps({"version": 1, "seen_ids": ["seen"]}),
                encoding="utf-8",
            )
            result = bridge.run()
            rows = [
                json.loads(line)
                for line in result.data_files[0].read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            state_before_acknowledge = json.loads(
                bridge.state_file.read_text(encoding="utf-8")
            )

        self.assertEqual([row["id"] for row in rows], ["new"])
        self.assertEqual(state_before_acknowledge["seen_ids"], ["seen"])

    def test_search_failure_returns_failed_result(self):
        reddit = FakeReddit(
            {
                ("all", "AI"): RuntimeError("API denied"),
                ("all", "LLM"): [],
                ("LocalLLaMA", "AI"): [],
                ("LocalLLaMA", "LLM"): [],
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, reddit)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("API denied", result.error)

    def test_no_new_content_is_failure(self):
        reddit = FakeReddit(
            {
                ("all", "AI"): [],
                ("all", "LLM"): [],
                ("LocalLLaMA", "AI"): [],
                ("LocalLLaMA", "LLM"): [],
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, reddit)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("没有新的内容", result.error)


if __name__ == "__main__":
    unittest.main()
