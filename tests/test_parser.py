import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.parser import load_articles


class ParserTest(unittest.TestCase):
    def write_jsonl(self, path: Path, rows):
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_loads_xhs_content_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "search_contents_2026-07-22.jsonl"
            self.write_jsonl(
                data_file,
                [{
                    "title": "小红书标题",
                    "desc": "小红书正文",
                    "note_url": "https://www.xiaohongshu.com/explore/note-1",
                    "nickname": "作者甲",
                    "liked_count": "1.2万",
                    "collected_count": "23",
                    "comment_count": "4",
                    "share_count": "5",
                    "time": 1_700_000_000_000,
                }],
            )
            with patch("utils.parser.config.CRAWL_LIMIT", 20):
                articles = load_articles(
                    [data_file], platform="xhs", allow_manual_fallback=False
                )

        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article["content"], "小红书正文")
        self.assertEqual(article["source"], "小红书")
        self.assertEqual(article["author"], "作者甲")
        self.assertEqual(article["likes"], 12_000)
        self.assertEqual(article["collects"], 23)

    def test_loads_zhihu_content_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "search_contents_2026-07-22.jsonl"
            self.write_jsonl(
                data_file,
                [{
                    "title": "知乎标题",
                    "content_text": "知乎正文",
                    "content_url": "https://www.zhihu.com/question/1/answer/2",
                    "user_nickname": "作者乙",
                    "voteup_count": 88,
                    "comment_count": 6,
                    "created_time": 1_700_000_000,
                }],
            )
            with patch("utils.parser.config.CRAWL_LIMIT", 20):
                articles = load_articles(
                    [data_file], platform="zhihu", allow_manual_fallback=False
                )

        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article["content"], "知乎正文")
        self.assertEqual(article["source"], "知乎")
        self.assertEqual(article["url"], "https://www.zhihu.com/question/1/answer/2")
        self.assertEqual(article["author"], "作者乙")
        self.assertEqual(article["likes"], 88)

    def test_loads_twscrape_x_fields_and_timezone(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "search_contents_2026-07-22.jsonl"
            self.write_jsonl(
                data_file,
                [{
                    "title": "X 标题",
                    "content": "X 正文",
                    "source": "X (Twitter)",
                    "url": "https://x.com/alice/status/1",
                    "author": "Alice",
                    "like_count": 19,
                    "comment_count": 4,
                    "publish_time": "2026-07-22T08:30:00+00:00",
                }],
            )
            with patch("utils.parser.config.CRAWL_LIMIT", 20):
                articles = load_articles(
                    [data_file], platform="x", allow_manual_fallback=False
                )

        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article["source"], "X (Twitter)")
        self.assertEqual(article["content"], "X 正文")
        self.assertEqual(article["author"], "Alice")
        self.assertEqual(article["likes"], 19)
        self.assertEqual(article["publish_time"].utcoffset().total_seconds(), 0)

    def test_loads_reddit_fields_without_treating_score_as_likes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "search_contents_2026-07-23.jsonl"
            self.write_jsonl(
                data_file,
                [{
                    "id": "abc123",
                    "title": "Reddit 标题",
                    "content": "Reddit 正文",
                    "source": "Reddit",
                    "url": "https://www.reddit.com/r/test/comments/abc123/example/",
                    "author": "alice",
                    "subreddit": "test",
                    "score": 123,
                    "upvote_ratio": 0.95,
                    "comment_count": 8,
                    "publish_time": "2026-07-23T08:30:00+00:00",
                }],
            )
            with patch("utils.parser.config.CRAWL_LIMIT", 20):
                articles = load_articles(
                    [data_file],
                    platform="reddit",
                    allow_manual_fallback=False,
                )

        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article["source"], "Reddit")
        self.assertEqual(article["content"], "Reddit 正文")
        self.assertEqual(article["comments"], 8)
        self.assertEqual(article["likes"], 0)
        self.assertEqual(article["raw"]["score"], 123)
        self.assertEqual(article["raw"]["upvote_ratio"], 0.95)

    def test_ignores_comment_files_and_does_not_scan_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_file = root / "search_contents_2026-07-22.jsonl"
            comments_file = root / "search_comments_2026-07-22.jsonl"
            historical_file = root / "search_contents_2026-07-21.jsonl"
            self.write_jsonl(current_file, [{"title": "本次", "desc": "正文"}])
            self.write_jsonl(comments_file, [{"content": "评论"}])
            self.write_jsonl(historical_file, [{"title": "历史", "desc": "旧正文"}])

            with patch("utils.parser.config.CRAWL_LIMIT", 20):
                articles = load_articles(
                    [current_file, comments_file],
                    platform="xhs",
                    allow_manual_fallback=False,
                )

        self.assertEqual([article["title"] for article in articles], ["本次"])


if __name__ == "__main__":
    unittest.main()
