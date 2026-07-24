import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from crawler.twscrape_bridge import TwscrapeBridge


class FakeAPI:
    def __init__(self, results, replies=None):
        self.results = results
        self.replies = replies or {}
        self.calls = []
        self.reply_calls = []
        self.factory_kwargs = None

    async def search(self, query, limit, kv):
        self.calls.append((query, limit, kv))
        result = self.results[query]
        if isinstance(result, Exception):
            raise result
        for tweet in result[:limit]:
            yield tweet

    async def tweet_replies(self, tweet_id, limit):
        self.reply_calls.append((tweet_id, limit))
        result = self.replies.get(str(tweet_id), [])
        if isinstance(result, Exception):
            raise result
        for tweet in result[:limit]:
            yield tweet


def make_tweet(tweet_id, text, hour, user="alice"):
    return SimpleNamespace(
        id=int(tweet_id),
        id_str=str(tweet_id),
        url=f"https://x.com/{user}/status/{tweet_id}",
        date=datetime(2026, 7, 22, hour, tzinfo=timezone.utc),
        rawContent=text,
        user=SimpleNamespace(username=user, displayname=user.title()),
        lang="en",
        likeCount=12,
        replyCount=3,
        retweetCount=4,
        bookmarkedCount=2,
        quoteCount=1,
        viewCount=100,
        conversationId=int(tweet_id),
        conversationIdStr=str(tweet_id),
        inReplyToTweetId=None,
        inReplyToTweetIdStr=None,
        retweetedTweet=None,
        quotedTweet=None,
        isQuoteStatus=False,
        possibly_sensitive=False,
        hashtags=["AI"],
        links=[
            SimpleNamespace(
                url="https://github.com/example/project",
                text="github.com/example/project",
                tcourl="https://t.co/example",
            )
        ],
    )


def make_reply(tweet_id, parent_id, text, likes, user):
    reply = make_tweet(tweet_id, text, 11, user=user)
    reply.likeCount = likes
    reply.inReplyToTweetId = int(parent_id)
    reply.inReplyToTweetIdStr = str(parent_id)
    return reply


class TwscrapeBridgeTest(unittest.TestCase):
    def make_bridge(self, temp_dir, api):
        def api_factory(**kwargs):
            api.factory_kwargs = kwargs
            return api

        bridge = TwscrapeBridge(
            api_factory=api_factory,
            now_provider=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
        )
        root = Path(temp_dir)
        bridge.configured_platform = "x"
        bridge.db_file = root / "twscrape.db"
        bridge.state_file = root / "state" / "seen.json"
        bridge.target_data_dir = root / "data"
        bridge.keywords = ["AI", "LLM"]
        bridge.limit = 3
        bridge.per_query_limit = 3
        bridge.lookback_hours = 168
        bridge.validate = lambda: []
        return bridge

    def write_session_db(self, path, cookies, active=1):
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE accounts "
                "(username TEXT, active INTEGER, cookies TEXT)"
            )
            connection.execute(
                "INSERT INTO accounts VALUES (?, ?, ?)",
                ("test-account", active, json.dumps(cookies)),
            )
        if os.name != "nt":
            path.chmod(0o600)

    def test_validate_requires_dependency_and_local_session(self):
        bridge = TwscrapeBridge()
        bridge.configured_platform = "x"
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.db_file = Path(temp_dir) / "missing.db"
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            with patch(
                "crawler.twscrape_bridge.importlib.util.find_spec",
                return_value=None,
            ):
                errors = bridge.validate()

        self.assertTrue(any("缺少 twscrape" in error for error in errors))
        self.assertTrue(any("会话数据库不存在" in error for error in errors))

    def test_validate_reads_active_cookie_account_without_mutating_database(self):
        bridge = TwscrapeBridge()
        bridge.configured_platform = "x"
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.db_file = Path(temp_dir) / "session.db"
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            self.write_session_db(
                bridge.db_file,
                {"auth_token": "test", "ct0": "test"},
            )
            errors = bridge.validate()

        self.assertEqual(errors, [])

    def test_validate_rejects_incomplete_cookie_account(self):
        bridge = TwscrapeBridge()
        bridge.configured_platform = "x"
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.db_file = Path(temp_dir) / "session.db"
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            self.write_session_db(bridge.db_file, {"auth_token": "test"})
            errors = bridge.validate()

        self.assertTrue(any("缺少 auth_token 或 ct0" in error for error in errors))

    def test_run_uses_real_api_shape_deduplicates_sorts_and_writes_current_run(self):
        api = FakeAPI(
            {
                "AI": [make_tweet("1", "newest", 10), make_tweet("2", "older", 8)],
                "LLM": [make_tweet("2", "duplicate", 8), make_tweet("4", "middle", 9)],
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, api)
            result = bridge.run()

            self.assertTrue(result.success)
            rows = [
                json.loads(line)
                for line in result.data_files[0].read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["id"] for row in rows], ["1", "4", "2"])
            self.assertEqual(rows[0]["source"], "X (Twitter)")
            self.assertEqual(rows[0]["url"], "https://x.com/alice/status/1")
            self.assertEqual(rows[2]["matched_keywords"], ["AI", "LLM"])
            self.assertEqual(
                rows[0]["referenced_urls"][0]["url"],
                "https://github.com/example/project",
            )
            self.assertFalse(rows[0]["platform_metadata"]["is_reply"])
            self.assertFalse(rows[0]["platform_metadata"]["is_retweet"])
            self.assertEqual(
                api.calls,
                [
                    ("AI", 3, {"product": "Latest"}),
                    ("LLM", 3, {"product": "Latest"}),
                ],
            )
            self.assertEqual(api.factory_kwargs["pool"], str(bridge.db_file))
            self.assertTrue(api.factory_kwargs["raise_when_no_account"])
            self.assertFalse(bridge.state_file.exists())

            self.assertEqual(bridge.acknowledge(), "")
            state = json.loads(bridge.state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["seen_ids"], ["1", "4", "2"])

    def test_search_failure_returns_failed_result(self):
        api = FakeAPI({"AI": RuntimeError("search broke"), "LLM": []})
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, api)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("search broke", result.error)

    def test_seen_ids_are_skipped_and_not_changed_by_collection_only(self):
        api = FakeAPI(
            {
                "AI": [make_tweet("1", "seen", 10), make_tweet("2", "new", 9)],
                "LLM": [],
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, api)
            bridge.state_file.parent.mkdir(parents=True)
            bridge.state_file.write_text(
                json.dumps({"version": 1, "seen_ids": ["1"]}),
                encoding="utf-8",
            )
            result = bridge.run()
            rows = [
                json.loads(line)
                for line in result.data_files[0].read_text(encoding="utf-8").splitlines()
            ]
            state_before_acknowledge = json.loads(
                bridge.state_file.read_text(encoding="utf-8")
            )

        self.assertEqual([row["id"] for row in rows], ["2"])
        self.assertEqual(state_before_acknowledge["seen_ids"], ["1"])

    def test_posts_outside_lookback_window_are_skipped(self):
        old_tweet = make_tweet("1", "old", 1)
        old_tweet.date = datetime(2026, 7, 10, tzinfo=timezone.utc)
        api = FakeAPI(
            {
                "AI": [old_tweet, make_tweet("2", "new", 9)],
                "LLM": [],
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, api)
            result = bridge.run()
            rows = [
                json.loads(line)
                for line in result.data_files[0].read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual([row["id"] for row in rows], ["2"])

    def test_fetch_comments_normalizes_sorts_and_limits_direct_replies(self):
        nested_reply = make_reply("13", "99", "nested", 100, "other")
        empty_reply = make_reply("14", "1", "", 90, "other")
        api = FakeAPI(
            {"AI": [], "LLM": []},
            replies={
                "1": [
                    make_reply("11", "1", "low", 2, "reader"),
                    make_reply("12", "1", "high", 20, "alice"),
                    nested_reply,
                    empty_reply,
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, api)
            results = bridge.fetch_comments(
                [
                    {
                        "id": "x:1",
                        "platform_item_id": "1",
                        "username": "alice",
                    }
                ],
                limit=2,
                timeout_seconds=5,
            )

        self.assertTrue(results["x:1"].available)
        self.assertEqual(
            [comment["id"] for comment in results["x:1"].comments],
            ["12", "11"],
        )
        self.assertTrue(results["x:1"].comments[0]["is_original_author"])
        self.assertEqual(api.reply_calls, [(1, 2)])

    def test_fetch_comments_isolates_failure_by_tweet(self):
        api = FakeAPI(
            {"AI": [], "LLM": []},
            replies={
                "1": RuntimeError("unavailable"),
                "2": [make_reply("21", "2", "reply", 1, "reader")],
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, api)
            results = bridge.fetch_comments(
                [
                    {
                        "id": "x:1",
                        "platform_item_id": "1",
                        "username": "alice",
                    },
                    {
                        "id": "x:2",
                        "platform_item_id": "2",
                        "username": "alice",
                    },
                ],
                limit=20,
                timeout_seconds=5,
            )

        self.assertFalse(results["x:1"].available)
        self.assertNotIn("unavailable", results["x:1"].error)
        self.assertTrue(results["x:2"].available)
        self.assertEqual(results["x:2"].comments[0]["id"], "21")


if __name__ == "__main__":
    unittest.main()
