import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from analyzer.filter import recent_keyword_filter


class RecentKeywordFilterTest(unittest.TestCase):
    def test_keeps_only_recent_keyword_matches_and_sorts_recent_first(self):
        now = datetime(2026, 7, 25, 12, 0)
        articles = [
            {"title": "旧的 AI Agent", "content": "内容", "publish_time": now - timedelta(days=4)},
            {"title": "无关内容", "content": "旅游", "publish_time": now - timedelta(hours=1)},
            {"title": "最新 LLM", "content": "AI Agent 实践", "publish_time": now - timedelta(hours=2)},
            {"title": "没有时间", "content": "AI Agent"},
            {"title": "较新智能体", "content": "智能体工具", "publish_time": now - timedelta(hours=3)},
        ]
        with patch("analyzer.filter.config.CONTENT_SEARCH_KEYWORDS", ["AI Agent", "智能体"]):
            kept, stats = recent_keyword_filter(articles, now=now, max_items=10)

        self.assertEqual([item["title"] for item in kept], ["最新 LLM", "较新智能体"])
        self.assertEqual(stats["dropped_old"], 1)
        self.assertEqual(stats["dropped_unrelated"], 1)
        self.assertEqual(stats["dropped_missing_time"], 1)
        self.assertEqual(kept[0]["_recent_keyword_matches"], ["ai agent"])

    def test_records_topic_and_intent_matches(self):
        now = datetime(2026, 7, 25, 12, 0)
        articles = [{
            "title": "Agent 架构复盘",
            "content": "AI Agent 架构和生产环境部署的实践",
            "publish_time": now - timedelta(hours=1),
        }]
        with patch("analyzer.filter.config.CONTENT_SEARCH_KEYWORDS", ["AI Agent"]), patch(
            "analyzer.filter.config.CONTENT_SEARCH_INTENTS",
            {
                "technical_research": ["架构"],
                "engineering_practice": ["生产环境"],
            },
        ):
            kept, _ = recent_keyword_filter(articles, now=now, max_items=10)

        self.assertEqual(
            [(item["intent_group"], item["intent_keyword"]) for item in kept[0]["_retrieval_matches"]],
            [("technical_research", "架构"), ("engineering_practice", "生产环境")],
        )
    def test_caps_results_after_sorting(self):
        now = datetime(2026, 7, 25, 12, 0)
        articles = [
            {"title": f"AI Agent {index}", "content": "", "publish_time": now - timedelta(hours=index)}
            for index in range(3)
        ]
        with patch("analyzer.filter.config.CONTENT_SEARCH_KEYWORDS", ["AI Agent"]):
            kept, stats = recent_keyword_filter(articles, now=now, max_items=2)

        self.assertEqual([item["title"] for item in kept], ["AI Agent 0", "AI Agent 1"])
        self.assertEqual(stats["truncated"], 1)


if __name__ == "__main__":
    unittest.main()
