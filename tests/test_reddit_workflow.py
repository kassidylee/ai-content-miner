import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from crawler.base import CrawlRunResult
from workflows import reddit


def article():
    return {
        "title": "Reddit item",
        "content": "Technical content",
        "url": "https://www.reddit.com/r/test/comments/abc123/example/",
        "raw": {"id": "abc123", "subreddit": "test"},
        "reddit_filter_metadata": {
            "stages": [],
            "final_decision": "keep",
            "final_reason_codes": ["REDDIT_FILTER_PIPELINE_PASSED"],
        },
    }


def result_record():
    return {
        "id": "reddit:abc123",
        "platform": "reddit",
        "title": "Reddit item",
        "abstract": "Technical content",
        "source_url": (
            "https://www.reddit.com/r/test/comments/abc123/example/"
        ),
        "subreddit": "test",
        "score": 8.0,
        "filter_metadata": {"final_decision": "keep"},
    }


def bridge(acknowledge=None):
    return SimpleNamespace(
        platform="reddit",
        validate=lambda: [],
        run=lambda: CrawlRunResult(
            success=True,
            data_files=(Path("current.jsonl"),),
        ),
        acknowledge=acknowledge or MagicMock(return_value=""),
    )


class RedditWorkflowTest(unittest.TestCase):
    def test_runtime_config_does_not_require_report_hosting_or_cos(self):
        active_bridge = bridge()
        with patch(
            "workflows.reddit.importlib.util.find_spec",
            return_value=object(),
        ), patch(
            "workflows.reddit.validate_reddit_rule_config",
        ), patch(
            "workflows.reddit.validate_reddit_embedding_config",
        ), patch(
            "workflows.reddit.validate_reddit_quality_config",
        ), patch(
            "workflows.reddit.validate_reddit_pipeline_config",
        ), patch(
            "workflows.reddit.validate_reddit_enrichment_config",
        ), patch(
            "workflows.reddit.validate_reddit_wecom_config",
            return_value=[],
        ), patch.object(
            reddit.config,
            "API_KEY",
            "test-key",
        ), patch.object(
            reddit.config,
            "BASE_URL",
            "https://api.example.com/v1",
        ), patch.object(
            reddit.config,
            "MODEL_NAME",
            "test-model",
        ), patch.object(
            reddit.config,
            "EMBEDDING_PROVIDER",
            "openai",
        ), patch.object(
            reddit.config,
            "REDDIT_FEED_RETENTION_DAYS",
            30,
        ), patch.object(
            reddit.config,
            "REDDIT_FEED_MAX_ITEMS",
            200,
        ), patch.object(
            reddit.config,
            "REPORT_BASE_URL",
            "",
        ), patch.object(
            reddit.config,
            "COS_SECRET_ID",
            "",
            create=True,
        ), patch.object(
            reddit.config,
            "COS_SECRET_KEY",
            "",
            create=True,
        ):
            errors = reddit.validate_reddit_runtime_config(active_bridge)

        self.assertEqual(errors, [])

    def test_success_stores_renders_acknowledges_then_notifies(self):
        item = article()
        record = result_record()
        events = []
        active_bridge = bridge(
            acknowledge=lambda: events.append("acknowledge") or ""
        )
        filtered = {
            "all_items": [item],
            "passed": [item],
            "dropped": [],
        }

        def notify(_items):
            events.append("notify")
            return True

        with patch(
            "workflows.reddit.load_articles",
            return_value=[item],
        ), patch(
            "workflows.reddit.run_reddit_filters",
            return_value=filtered,
        ), patch(
            "workflows.reddit._print_filter_results",
        ), patch(
            "workflows.reddit.enrich_reddit_items",
            return_value=[item],
        ), patch(
            "workflows.reddit.build_reddit_result",
            return_value=record,
        ), patch(
            "workflows.reddit.append_reddit_results",
            return_value=Path("data/processed/reddit.jsonl"),
        ) as store, patch(
            "workflows.reddit.render_reddit_feed",
            return_value=Path("reports/reddit.html"),
        ) as render, patch.object(
            reddit.config,
            "REDDIT_ENABLE_WECOM",
            True,
        ), patch(
            "workflows.reddit.send_reddit_wecom",
            side_effect=notify,
        ):
            exit_code = reddit.run_reddit_workflow(active_bridge)

        self.assertEqual(exit_code, reddit.EXIT_OK)
        store.assert_called_once_with([record])
        render.assert_called_once_with()
        self.assertEqual(events, ["acknowledge", "notify"])

    def test_notification_failure_keeps_results_and_acknowledged_state(self):
        item = article()
        record = result_record()
        events = []
        active_bridge = bridge(
            acknowledge=lambda: events.append("acknowledge") or ""
        )
        filtered = {
            "all_items": [item],
            "passed": [item],
            "dropped": [],
        }
        with patch(
            "workflows.reddit.load_articles",
            return_value=[item],
        ), patch(
            "workflows.reddit.run_reddit_filters",
            return_value=filtered,
        ), patch(
            "workflows.reddit._print_filter_results",
        ), patch(
            "workflows.reddit.enrich_reddit_items",
            return_value=[item],
        ), patch(
            "workflows.reddit.build_reddit_result",
            return_value=record,
        ), patch(
            "workflows.reddit.append_reddit_results",
            return_value=Path("data/processed/reddit.jsonl"),
        ), patch(
            "workflows.reddit.render_reddit_feed",
            return_value=Path("reports/reddit.html"),
        ), patch.object(
            reddit.config,
            "REDDIT_ENABLE_WECOM",
            True,
        ), patch(
            "workflows.reddit.send_reddit_wecom",
            side_effect=lambda _items: events.append("notify") or False,
        ):
            exit_code = reddit.run_reddit_workflow(active_bridge)

        self.assertEqual(exit_code, reddit.EXIT_NOTIFY)
        self.assertEqual(events, ["acknowledge", "notify"])


if __name__ == "__main__":
    unittest.main()
