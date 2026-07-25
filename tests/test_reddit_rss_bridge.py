import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from crawler.reddit_rss_bridge import RedditRssBridge


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


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


def atom_entry(
    post_id,
    title,
    published,
    subreddit="MachineLearning",
    body="正文",
    author="/u/alice",
    external_url="",
):
    post_url = (
        f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/example/"
    )
    external_link = external_url or post_url
    content_html = (
        f'<!-- SC_OFF --><div class="md"><p>{body}</p></div><!-- SC_ON --> '
        f'submitted by <a href="https://www.reddit.com/user/alice">{author}</a>'
        f'<br/><span><a href="{external_link}">[link]</a></span>'
        f'<span><a href="{post_url}">[comments]</a></span>'
    )
    return f"""
    <entry>
      <author><name>{escape(author)}</name></author>
      <category term="{escape(subreddit)}" label="r/{escape(subreddit)}"/>
      <content type="html">{escape(content_html)}</content>
      <id>t3_{escape(post_id)}</id>
      <link href="{escape(post_url)}"/>
      <updated>{published}</updated>
      <published>{published}</published>
      <title>{escape(title)}</title>
    </entry>
    """


def atom_feed(*entries):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:media="http://search.yahoo.com/mrss/">'
        + "".join(entries)
        + "</feed>"
    )


class RedditRssBridgeTest(unittest.TestCase):
    def make_bridge(self, temp_dir, requester, sleeps=None):
        sleep_calls = sleeps if sleeps is not None else []
        bridge = RedditRssBridge(
            requester=requester,
            now_provider=lambda: datetime(
                2026, 7, 24, 12, tzinfo=timezone.utc
            ),
            sleeper=sleep_calls.append,
        )
        root = Path(temp_dir)
        bridge.configured_platform = "reddit"
        bridge.user_agent = "python:ai-content-miner:test (contact: example.com)"
        bridge.state_file = root / "state" / "seen.json"
        bridge.target_data_dir = root / "data"
        bridge.keywords = ["AI", "LLM"]
        bridge.subreddits = ["MachineLearning", "LocalLLaMA"]
        bridge.limit = 3
        bridge.per_subreddit_limit = 10
        bridge.lookback_hours = 168
        bridge.request_interval = 31
        bridge.max_response_bytes = 1_000_000
        return bridge

    def test_validate_requires_explicit_subreddit_and_user_agent(self):
        bridge = RedditRssBridge()
        bridge.configured_platform = "reddit"
        bridge.subreddits = ["all"]
        bridge.user_agent = ""
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.state_file = Path(temp_dir) / "missing-state.json"
            errors = bridge.validate()

        self.assertTrue(any("不使用 all" in error for error in errors))
        self.assertTrue(any("REDDIT_RSS_USER_AGENT" in error for error in errors))
        self.assertFalse(any("CLIENT_ID" in error for error in errors))
        self.assertFalse(any("PRAW" in error for error in errors))

    def test_run_parses_atom_filters_deduplicates_and_preserves_limitations(self):
        duplicate = atom_entry(
            "2",
            "LLM older duplicate",
            "2026-07-24T08:00:00+00:00",
        )
        requester = FakeRequester(
            {
                "MachineLearning": FakeResponse(
                    text=atom_feed(
                        atom_entry(
                            "1",
                            "AI newest",
                            "2026-07-24T11:00:00+00:00",
                            body="正文与 AI",
                            external_url="https://example.com/paper",
                        ),
                        duplicate,
                        atom_entry(
                            "ignored",
                            "unrelated",
                            "2026-07-24T10:00:00+00:00",
                            body="other",
                        ),
                    ),
                    headers={
                        "x-ratelimit-remaining": "0.0",
                        "x-ratelimit-reset": "30",
                    },
                ),
                "LocalLLaMA": FakeResponse(
                    text=atom_feed(
                        atom_entry(
                            "3",
                            "middle",
                            "2026-07-24T10:00:00+00:00",
                            subreddit="LocalLLaMA",
                            body="AI and LLM",
                        ),
                        duplicate,
                    )
                ),
            }
        )
        sleeps = []

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, requester, sleeps)
            result = bridge.run()

            self.assertTrue(result.success)
            rows = [
                json.loads(line)
                for line in result.data_files[0].read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual([row["id"] for row in rows], ["1", "3", "2"])
            self.assertEqual(rows[0]["content"], "正文与 AI")
            self.assertEqual(rows[0]["external_url"], "https://example.com/paper")
            self.assertEqual(rows[0]["author"], "alice")
            self.assertIsNone(rows[0]["score"])
            self.assertIsNone(rows[0]["upvote_ratio"])
            self.assertIsNone(rows[0]["comment_count"])
            self.assertFalse(rows[0]["metrics_available"])
            self.assertEqual(rows[0]["collection_method"], "reddit_rss")
            self.assertEqual(rows[1]["matched_keywords"], ["AI", "LLM"])
            self.assertFalse(bridge.state_file.exists())

            self.assertEqual(sleeps, [31.0])
            self.assertEqual(len(requester.calls), 2)
            for url, kwargs in requester.calls:
                self.assertTrue(url.endswith("/new/.rss"))
                self.assertEqual(kwargs["params"], {"limit": 10})
                self.assertIn("application/atom+xml", kwargs["headers"]["Accept"])
                self.assertEqual(kwargs["timeout"], 30.0)

            self.assertEqual(bridge.acknowledge(), "")
            state = json.loads(bridge.state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["seen_ids"], ["1", "3", "2"])

    def test_seen_and_old_entries_are_skipped(self):
        requester = FakeRequester(
            {
                "MachineLearning": FakeResponse(
                    text=atom_feed(
                        atom_entry(
                            "seen",
                            "AI seen",
                            "2026-07-24T11:00:00+00:00",
                        ),
                        atom_entry(
                            "old",
                            "AI old",
                            "2026-07-01T11:00:00+00:00",
                        ),
                        atom_entry(
                            "new",
                            "LLM new",
                            "2026-07-24T10:00:00+00:00",
                        ),
                    )
                ),
                "LocalLLaMA": FakeResponse(text=atom_feed()),
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

    def test_partial_rate_limit_keeps_successful_community(self):
        requester = FakeRequester(
            {
                "MachineLearning": FakeResponse(
                    status_code=429,
                    headers={"x-ratelimit-reset": "30"},
                ),
                "LocalLLaMA": FakeResponse(
                    text=atom_feed(
                        atom_entry(
                            "1",
                            "AI available",
                            "2026-07-24T11:00:00+00:00",
                            subreddit="LocalLLaMA",
                        )
                    )
                ),
            }
        )
        sleeps = []

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, requester, sleeps)
            result = bridge.run()

        self.assertTrue(result.success)
        self.assertEqual(sleeps, [31.0])

    def test_all_communities_rate_limited_returns_failed_result(self):
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
        self.assertIn("建议等待 60 秒", result.error)

    def test_invalid_xml_returns_failed_result(self):
        requester = FakeRequester(
            {
                "MachineLearning": FakeResponse(text="<not-closed>"),
                "LocalLLaMA": FakeResponse(text="<not-closed>"),
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, requester)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("未返回合法 Atom XML", result.error)

    def test_non_atom_xml_returns_failed_result(self):
        requester = FakeRequester(
            {
                "MachineLearning": FakeResponse(text="<rss></rss>"),
                "LocalLLaMA": FakeResponse(text="<rss></rss>"),
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = self.make_bridge(temp_dir, requester)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertIn("根节点不是 Atom feed", result.error)


if __name__ == "__main__":
    unittest.main()
