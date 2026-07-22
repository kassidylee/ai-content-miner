import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from crawler.twikit_bridge import TwikitBridge


class FakeHttpClient:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


class FakeResult(list):
    def __init__(self, rows, next_page=None):
        super().__init__(rows)
        self._next_page = next_page
        self.next_cursor = "next-page" if next_page is not None else None
        self.next_called = 0

    async def next(self):
        self.next_called += 1
        return self._next_page or FakeResult([])


class FakeClient:
    def __init__(self, results):
        self.results = results
        self.http = FakeHttpClient()
        self.loaded_cookie = None
        self.calls = []

    def load_cookies(self, path):
        self.loaded_cookie = path

    async def search_tweet(self, query, product, count):
        self.calls.append((query, product, count))
        result = self.results[query]
        if isinstance(result, Exception):
            raise result
        return result


def make_tweet(tweet_id, text, hour, user="alice"):
    return SimpleNamespace(
        id=str(tweet_id),
        full_text=text,
        text=text,
        created_at_datetime=datetime(2026, 7, 22, hour, tzinfo=timezone.utc),
        user=SimpleNamespace(screen_name=user, name=user.title()),
        lang="en",
        favorite_count=12,
        reply_count=3,
        retweet_count=4,
        bookmark_count=2,
        quote_count=1,
        view_count=100,
    )


class TwikitBridgeTest(unittest.TestCase):
    def make_bridge(self, temp_dir, client):
        bridge = TwikitBridge(
            client_factory=lambda **kwargs: client,
            now_provider=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
        )
        root = Path(temp_dir)
        bridge.configured_platform = "x"
        bridge.cookie_file = root / "cookies.json"
        bridge.cookie_file.write_text(
            json.dumps({"auth_token": "test", "ct0": "test"}),
            encoding="utf-8",
        )
        bridge.state_file = root / "state" / "seen.json"
        bridge.target_data_dir = root / "data"
        bridge.keywords = ["AI", "LLM"]
        bridge.limit = 3
        bridge.per_query_limit = 3
        bridge.max_pages = 2
        bridge.lookback_hours = 168
        bridge.validate = lambda: []
        return bridge

    def test_validate_requires_dependency_and_local_cookie(self):
        bridge = TwikitBridge()
        bridge.configured_platform = "x"
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.cookie_file = Path(temp_dir) / "missing.json"
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            with patch(
                "crawler.twikit_bridge.importlib.util.find_spec", return_value=None
            ):
                errors = bridge.validate()

        self.assertTrue(any("缺少 Twikit" in error for error in errors))
        self.assertTrue(any("Cookie 文件不存在" in error for error in errors))

    def test_validate_rejects_python_39_for_twikit(self):
        bridge = TwikitBridge()
        bridge.configured_platform = "x"
        version_info = type(
            "VersionInfo",
            (),
            {"major": 3, "minor": 9, "__lt__": lambda self, other: True},
        )()
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.cookie_file = Path(temp_dir) / "cookies.json"
            bridge.cookie_file.write_text(
                json.dumps({"auth_token": "test", "ct0": "test"}),
                encoding="utf-8",
            )
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            with patch(
                "crawler.twikit_bridge.sys.version_info",
                version_info,
            ), patch(
                "crawler.twikit_bridge.importlib.util.find_spec",
                return_value=object(),
            ), patch("crawler.twikit_bridge.metadata.version", return_value="2.3.3"):
                errors = bridge.validate()

        self.assertTrue(any("Python >=3.10" in error for error in errors))

    def test_validate_rejects_wrong_twikit_version_and_bad_cookie(self):
        bridge = TwikitBridge()
        bridge.configured_platform = "x"
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.cookie_file = Path(temp_dir) / "cookies.json"
            bridge.cookie_file.write_text('{"auth_token": "test"}', encoding="utf-8")
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            with patch(
                "crawler.twikit_bridge.importlib.util.find_spec",
                return_value=object(),
            ), patch("crawler.twikit_bridge.metadata.version", return_value="2.2.0"):
                errors = bridge.validate()

        self.assertTrue(any("版本不匹配" in error for error in errors))
        self.assertTrue(any("ct0" in error for error in errors))

    def test_run_paginates_deduplicates_sorts_and_writes_only_current_run(self):
        second_page = FakeResult([make_tweet("3", "older page", 7)])
        first_page = FakeResult(
            [make_tweet("1", "newest", 10), make_tweet("2", "duplicate", 8)],
            next_page=second_page,
        )
        client = FakeClient(
            {
                "AI": first_page,
                "LLM": FakeResult(
                    [make_tweet("2", "duplicate", 8), make_tweet("4", "middle", 9)]
                ),
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, client)
            result = bridge.run()

            self.assertTrue(result.success)
            self.assertEqual(len(result.data_files), 1)
            rows = [
                json.loads(line)
                for line in result.data_files[0].read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["id"] for row in rows], ["1", "4", "2"])
            self.assertEqual(rows[0]["source"], "X (Twitter)")
            self.assertEqual(rows[0]["url"], "https://x.com/alice/status/1")
            self.assertEqual(first_page.next_called, 1)
            self.assertEqual(
                client.calls,
                [("AI", "Latest", 3), ("LLM", "Latest", 3)],
            )
            self.assertTrue(client.http.closed)
            self.assertFalse(bridge.state_file.exists())

            self.assertEqual(bridge.acknowledge(), "")
            state = json.loads(bridge.state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["seen_ids"], ["1", "4", "2"])

    def test_seen_ids_are_not_written_or_returned_again_before_success(self):
        client = FakeClient(
            {
                "AI": FakeResult(
                    [make_tweet("1", "already seen", 10), make_tweet("5", "new", 9)]
                ),
                "LLM": FakeResult([]),
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, client)
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
            state_before_ack = json.loads(
                bridge.state_file.read_text(encoding="utf-8")
            )

        self.assertEqual([row["id"] for row in rows], ["5"])
        self.assertEqual(state_before_ack["seen_ids"], ["1"])

    def test_search_failure_returns_failed_result_and_closes_client(self):
        client = FakeClient({"AI": RuntimeError("search broke"), "LLM": FakeResult([])})
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, client)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("search broke", result.error)
        self.assertTrue(client.http.closed)

    def test_posts_outside_lookback_window_are_skipped(self):
        old_tweet = make_tweet("old", "old post", 1)
        old_tweet.created_at_datetime = datetime(2026, 7, 10, tzinfo=timezone.utc)
        client = FakeClient(
            {
                "AI": FakeResult(
                    [old_tweet, make_tweet("new", "new post", 9)]
                ),
                "LLM": FakeResult([]),
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, client)
            result = bridge.run()
            rows = [
                json.loads(line)
                for line in result.data_files[0].read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual([row["id"] for row in rows], ["new"])


if __name__ == "__main__":
    unittest.main()
