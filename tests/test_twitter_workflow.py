import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from analyzer.twitter_embedding import TwitterEmbeddingError
from crawler.base import CrawlRunResult
from workflows import twitter


def make_item():
    return {
        "id": "x:1",
        "platform_item_id": "1",
        "platform": "x",
        "title": "title",
        "content": "content",
        "filter_metadata": {
            "stages": [],
            "final_decision": "pending",
            "final_reason_codes": [],
        },
        "processed_at": None,
    }


def make_bridge(acknowledge=None):
    return SimpleNamespace(
        platform="x",
        validate=lambda: [],
        run=lambda: CrawlRunResult(
            success=True,
            data_files=(Path("current.jsonl"),),
        ),
        acknowledge=acknowledge or MagicMock(return_value=""),
        fetch_replies=MagicMock(),
    )


class TwitterWorkflowTest(unittest.TestCase):
    def test_disabled_embedding_skips_embedding_config_validation(self):
        bridge = make_bridge()
        with patch.object(
            twitter.config,
            "TWITTER_EMBEDDING_ENABLED",
            False,
        ), patch(
            "workflows.twitter.validate_twitter_embedding_config",
            side_effect=TwitterEmbeddingError("must not be called"),
        ) as validate_embedding:
            twitter.validate_twitter_runtime_config(bridge)

        validate_embedding.assert_not_called()

    def test_twitter_wecom_is_optional_even_if_legacy_webhook_is_placeholder(self):
        bridge = make_bridge()
        with patch.object(twitter.config, "API_KEY", "real-key"), patch.object(
            twitter.config,
            "TWITTER_ENABLE_WECOM",
            False,
        ), patch.object(
            twitter.config,
            "WECOM_WEBHOOK",
            "https://example.com/hook",
        ):
            errors = twitter.validate_twitter_runtime_config(bridge)

        self.assertNotIn("WECOM_WEBHOOK", "\n".join(errors))

    def test_success_persists_and_renders_before_acknowledge(self):
        item = make_item()
        acknowledge = MagicMock(return_value="")
        bridge = make_bridge(acknowledge)
        filtered = {
            "all_items": [item],
            "passed": [item],
            "dropped": [],
        }
        with patch(
            "workflows.twitter.load_twitter_items",
            return_value=[item],
        ), patch(
            "workflows.twitter.run_twitter_filters",
            return_value=filtered,
        ), patch(
            "workflows.twitter.enrich_twitter_items",
            return_value=[item],
        ), patch(
            "workflows.twitter.append_twitter_results",
            return_value=Path("data/processed/x.jsonl"),
        ) as store, patch(
            "workflows.twitter.render_twitter_feed",
            return_value=Path("reports/x.html"),
        ) as render, patch.object(
            twitter.config,
            "TWITTER_ENABLE_WECOM",
            False,
        ):
            exit_code = twitter.run_twitter_workflow(bridge)

        self.assertEqual(exit_code, twitter.EXIT_OK)
        store.assert_called_once_with([item])
        render.assert_called_once_with()
        acknowledge.assert_called_once_with()
        self.assertEqual(
            item["filter_metadata"]["final_decision"],
            "keep",
        )

    def test_embedding_failure_does_not_store_render_or_acknowledge(self):
        item = make_item()
        acknowledge = MagicMock(return_value="")
        bridge = make_bridge(acknowledge)
        with patch(
            "workflows.twitter.load_twitter_items",
            return_value=[item],
        ), patch(
            "workflows.twitter.run_twitter_filters",
            side_effect=TwitterEmbeddingError("failed"),
        ), patch(
            "workflows.twitter.append_twitter_results"
        ) as store, patch(
            "workflows.twitter.render_twitter_feed"
        ) as render:
            exit_code = twitter.run_twitter_workflow(bridge)

        self.assertEqual(exit_code, twitter.EXIT_EMBEDDING)
        store.assert_not_called()
        render.assert_not_called()
        acknowledge.assert_not_called()

    def test_notification_failure_happens_after_acknowledge(self):
        item = make_item()
        events = []
        bridge = make_bridge(
            acknowledge=lambda: events.append("acknowledge") or ""
        )
        filtered = {
            "all_items": [item],
            "passed": [item],
            "dropped": [],
        }

        def notify(_items):
            events.append("notify")
            return False

        with patch(
            "workflows.twitter.load_twitter_items",
            return_value=[item],
        ), patch(
            "workflows.twitter.run_twitter_filters",
            return_value=filtered,
        ), patch(
            "workflows.twitter.enrich_twitter_items",
            return_value=[item],
        ), patch(
            "workflows.twitter.append_twitter_results",
            return_value=Path("data/processed/x.jsonl"),
        ), patch(
            "workflows.twitter.render_twitter_feed",
            return_value=Path("reports/x.html"),
        ), patch.object(
            twitter.config,
            "TWITTER_ENABLE_WECOM",
            True,
        ), patch(
            "workflows.twitter.send_twitter_wecom",
            side_effect=notify,
        ):
            exit_code = twitter.run_twitter_workflow(bridge)

        self.assertEqual(exit_code, twitter.EXIT_NOTIFY)
        self.assertEqual(events, ["acknowledge", "notify"])


if __name__ == "__main__":
    unittest.main()
