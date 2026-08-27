import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from crawler.reddit_bridge import RedditBridge


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, json_error=None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeRequester:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        subreddit = url.split("/r/", 1)[1].split("/", 1)[0]
        response = self.responses[subreddit]
        if isinstance(response, Exception):
            raise response
        return response


def make_post(
    post_id,
    title,
    hour,
    subreddit="MachineLearning",
    body="正文",
    **overrides,
):
    post = {
        "id": str(post_id),
        "title": title,
        "selftext": body,
        "created_utc": datetime(
            2026, 7, 24, hour, tzinfo=timezone.utc
        ).timestamp(),
        "author": "alice",
        "subreddit": subreddit,
        "permalink": f"/r/{subreddit}/comments/{post_id}/example/",
        "url": f"https://example.com/{post_id}",
        "score": 42,
        "upvote_ratio": 0.91,
        "num_comments": 7,
        "is_self": bool(body),
        "over_18": False,
        "link_flair_text": "Research",
        "domain": "self.MachineLearning" if body else "example.com",
    }
    post.update(overrides)
    return {"kind": "t3", "data": post}


def listing(*posts):
    return {"kind": "Listing", "data": {"children": list(posts), "after": None}}


class RedditBridgeTest(unittest.TestCase):
    def make_bridge(self, temp_dir, requester):
        bridge = RedditBridge(
            requester=requester,
            now_provider=lambda: datetime(
                2026, 7, 24, 12, tzinfo=timezone.utc
            ),
        )
        root = Path(temp_dir)
        bridge.configured_platform = "reddit"
        bridge.user_agent = "ai-content-miner/test (local JSON reader)"
        bridge.state_file = root / "state" / "seen.json"
        bridge.target_data_dir = root / "data"
        bridge.keywords = ["AI", "LLM"]
        bridge.subreddits = ["MachineLearning", "LocalLLaMA"]
        bridge.limit = 3
        bridge.per_subreddit_limit = 20
        bridge.lookback_hours = 168
        return bridge

    def test_validate_requires_explicit_subreddit_and_honest_user_agent(self):
        bridge = RedditBridge()
        bridge.configured_platform = "reddit"
        bridge.subreddits = ["all"]
        bridge.user_agent = ""
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            errors = bridge.validate()

        self.assertTrue(any("不使用 all" in error for error in errors))
        self.assertTrue(any("REDDIT_USER_AGENT" in error for error in errors))
        self.assertFalse(any("CLIENT_ID" in error for error in errors))
        self.assertFalse(any("PRAW" in error for error in errors))

    def test_validate_accepts_supported_configuration(self):
        bridge = RedditBridge()
        bridge.configured_platform = "reddit"
        bridge.subreddits = ["LocalLLaMA"]
        bridge.user_agent = "ai-content-miner/0.1 (local JSON reader)"
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            errors = bridge.validate()

        self.assertEqual(errors, [])

    def test_run_filters_locally_deduplicates_sorts_and_preserves_metrics(self):
        duplicate = make_post("2", "LLM older duplicate", 8)
        requester = FakeRequester(
            {
                "MachineLearning": FakeResponse(
                    payload=listing(
                        make_post("1", "AI newest", 11),
                        duplicate,
                        make_post("ignored", "unrelated title", 10, body="other"),
                    )
                ),
                "LocalLLaMA": FakeResponse(
                    payload=listing(
                        make_post(
                            "3",
                            "middle",
                            10,
                            subreddit="LocalLLaMA",
                            body="AI and LLM",
                        ),
                        duplicate,
                    )
                ),
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, requester)
            result = bridge.run()

            self.assertTrue(result.success)
            rows = [
                json.loads(line)
                for line in result.data_files[0].read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual([row["id"] for row in rows], ["1", "3", "2"])
            self.assertEqual(
                rows[0]["url"],
                "https://www.reddit.com/r/MachineLearning/comments/1/example/",
            )
            self.assertEqual(rows[0]["external_url"], "https://example.com/1")
            self.assertEqual(rows[0]["score"], 42)
            self.assertEqual(rows[0]["upvote_ratio"], 0.91)
            self.assertEqual(rows[0]["comment_count"], 7)
            self.assertEqual(rows[0]["collection_method"], "reddit_json")
            self.assertEqual(rows[1]["matched_keywords"], ["AI", "LLM"])
            self.assertFalse(bridge.state_file.exists())

            self.assertEqual(len(requester.calls), 2)
            for url, kwargs in requester.calls:
                self.assertTrue(url.endswith("/new.json"))
                self.assertEqual(kwargs["params"], {"limit": 20, "raw_json": 1})
                self.assertEqual(
                    kwargs["headers"]["User-Agent"],
                    "ai-content-miner/test (local JSON reader)",
                )
                self.assertEqual(kwargs["timeout"], 30.0)

            self.assertEqual(bridge.acknowledge(), "")
            state = json.loads(bridge.state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["seen_ids"], ["1", "3", "2"])

    def test_seen_and_old_posts_are_skipped(self):
        old_post = make_post("old", "AI too old", 1)
        old_post["data"]["created_utc"] = datetime(
            2026, 7, 1, tzinfo=timezone.utc
        ).timestamp()
        requester = FakeRequester(
            {
                "MachineLearning": FakeResponse(
                    payload=listing(
                        make_post("seen", "AI seen", 11),
                        old_post,
                        make_post("new", "LLM new", 10),
                    )
                ),
                "LocalLLaMA": FakeResponse(payload=listing()),
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, requester)
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

        self.assertEqual([row["id"] for row in rows], ["new"])

    def test_partial_subreddit_failure_keeps_successful_results(self):
        requester = FakeRequester(
            {
                "MachineLearning": FakeResponse(
                    status_code=429,
                    headers={"Retry-After": "60"},
                ),
                "LocalLLaMA": FakeResponse(
                    payload=listing(
                        make_post(
                            "1",
                            "AI available",
                            11,
                            subreddit="LocalLLaMA",
                        )
                    )
                ),
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, requester)
            result = bridge.run()

        self.assertTrue(result.success)

    def test_all_subreddits_rate_limited_returns_failed_result(self):
        requester = FakeRequester(
            {
                "MachineLearning": FakeResponse(
                    status_code=429,
                    headers={"Retry-After": "60"},
                ),
                "LocalLLaMA": FakeResponse(status_code=429),
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, requester)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("429", result.error)
        self.assertIn("Retry-After=60", result.error)

    def test_invalid_json_returns_failed_result(self):
        requester = FakeRequester(
            {
                "MachineLearning": FakeResponse(
                    json_error=ValueError("not json")
                ),
                "LocalLLaMA": FakeResponse(json_error=ValueError("not json")),
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, requester)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("未返回合法 JSON", result.error)


if __name__ == "__main__":
    unittest.main()
