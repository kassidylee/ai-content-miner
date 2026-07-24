import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import main
from analyzer.embedding_filter import EmbeddingFilterError
from crawler.base import CrawlRunResult
from output.feed_renderer import FeedRenderError
from utils.result_store import ResultStoreError


def make_item():
    return {
        "id": "x:1",
        "platform_item_id": "1",
        "platform": "x",
        "title": "test",
        "content": "test content",
        "filter_metadata": {
            "stages": [],
            "final_decision": "pending",
            "final_reason_codes": [],
        },
        "processed_at": None,
    }


def make_bridge(run_result=None, acknowledge=None, with_comments=False):
    bridge = SimpleNamespace(
        platform="x",
        validate=lambda: [],
        run=lambda: run_result
        or CrawlRunResult(success=True, data_files=(Path("current.jsonl"),)),
        acknowledge=acknowledge or MagicMock(return_value=""),
    )
    if with_comments:
        bridge.fetch_comments = MagicMock()
    return bridge


class MainTest(unittest.TestCase):
    def test_runtime_config_only_requires_wecom_when_enabled(self):
        bridge = SimpleNamespace(
            platform="x",
            validate=lambda: ["crawler-error"],
        )
        with patch.object(main.config, "API_KEY", "real-key"), patch.object(
            main.config,
            "ENABLE_WECOM",
            False,
        ), patch.object(
            main.config,
            "WECOM_WEBHOOK",
            "https://example.com/hook",
        ):
            errors = main.validate_runtime_config(bridge)

        self.assertNotIn("WECOM_WEBHOOK", "\n".join(errors))
        self.assertIn("crawler-error", errors)

        with patch.object(main.config, "API_KEY", "real-key"), patch.object(
            main.config,
            "ENABLE_WECOM",
            True,
        ), patch.object(
            main.config,
            "WECOM_WEBHOOK",
            "https://example.com/hook",
        ):
            enabled_errors = main.validate_runtime_config(bridge)

        self.assertIn("WECOM_WEBHOOK", "\n".join(enabled_errors))

    def test_runtime_config_validates_interest_topics_before_crawl(self):
        bridge = SimpleNamespace(platform="x", validate=lambda: [])
        with patch.object(main.config, "API_KEY", "real-key"), patch.object(
            main.config,
            "INTEREST_TOPICS",
            [],
        ):
            errors = main.validate_runtime_config(bridge)

        self.assertIn("INTEREST_TOPICS", "\n".join(errors))

    def test_crawler_failure_returns_nonzero_and_stops_pipeline(self):
        bridge = make_bridge(
            CrawlRunResult(success=False, error="crawler failed")
        )
        with patch("main.load_articles") as article_loader:
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, main.EXIT_CRAWLER)
        article_loader.assert_not_called()

    def test_empty_current_run_returns_nonzero(self):
        bridge = make_bridge()
        with patch("main.load_articles", return_value=[]):
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, main.EXIT_NO_DATA)

    def test_embedding_failure_does_not_store_render_or_acknowledge(self):
        item = make_item()
        acknowledge = MagicMock(return_value="")
        bridge = make_bridge(acknowledge=acknowledge)
        with patch("main.load_articles", return_value=[item]), patch(
            "main.run_filter_pipeline",
            side_effect=EmbeddingFilterError("failed"),
        ), patch("main.append_processed_items") as store, patch(
            "main.render_platform_feed"
        ) as render:
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, main.EXIT_EMBEDDING)
        store.assert_not_called()
        render.assert_not_called()
        acknowledge.assert_not_called()

    def test_success_persists_all_items_before_acknowledge(self):
        kept = make_item()
        dropped = make_item()
        dropped["id"] = "x:2"
        dropped["filter_metadata"]["final_decision"] = "drop"
        dropped["filter_metadata"]["final_reason_codes"] = ["RULE_EMPTY_CONTENT"]
        acknowledge = MagicMock(return_value="")
        bridge = make_bridge(acknowledge=acknowledge, with_comments=True)
        filtered = {
            "all_items": [kept, dropped],
            "passed": [kept],
            "dropped": [dropped],
        }

        with patch("main.load_articles", return_value=[kept, dropped]), patch(
            "main.run_filter_pipeline",
            return_value=filtered,
        ) as pipeline, patch(
            "main.enrich_items",
            return_value=[kept],
        ), patch(
            "main.append_processed_items",
            return_value=Path("data/processed/x.jsonl"),
        ) as store, patch(
            "main.render_platform_feed",
            return_value=Path("reports/x.html"),
        ), patch.object(
            main.config,
            "ENABLE_WECOM",
            False,
        ):
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, main.EXIT_OK)
        self.assertEqual(kept["filter_metadata"]["final_decision"], "keep")
        self.assertEqual(
            kept["filter_metadata"]["final_reason_codes"],
            ["FILTER_PIPELINE_PASSED"],
        )
        self.assertIsNotNone(kept["processed_at"])
        store.assert_called_once_with("x", [kept, dropped])
        self.assertIs(
            pipeline.call_args.kwargs["comment_provider"],
            bridge,
        )
        acknowledge.assert_called_once_with()

    def test_store_or_render_failure_does_not_acknowledge(self):
        item = make_item()
        filtered = {
            "all_items": [item],
            "passed": [item],
            "dropped": [],
        }
        for failure, expected_exit in [
            (ResultStoreError("store failed"), main.EXIT_STORE),
            (FeedRenderError("render failed"), main.EXIT_RENDER),
        ]:
            with self.subTest(expected_exit=expected_exit):
                acknowledge = MagicMock(return_value="")
                bridge = make_bridge(acknowledge=acknowledge)
                store_side_effect = (
                    failure if expected_exit == main.EXIT_STORE else None
                )
                render_side_effect = (
                    failure if expected_exit == main.EXIT_RENDER else None
                )
                with patch(
                    "main.load_articles",
                    return_value=[item],
                ), patch(
                    "main.run_filter_pipeline",
                    return_value=filtered,
                ), patch(
                    "main.enrich_items",
                    return_value=[item],
                ), patch(
                    "main.append_processed_items",
                    return_value=Path("data/processed/x.jsonl"),
                    side_effect=store_side_effect,
                ), patch(
                    "main.render_platform_feed",
                    return_value=Path("reports/x.html"),
                    side_effect=render_side_effect,
                ):
                    exit_code = main.run_workflow(bridge)

                self.assertEqual(exit_code, expected_exit)
                acknowledge.assert_not_called()

    def test_state_failure_after_output_returns_nonzero(self):
        item = make_item()
        bridge = make_bridge(acknowledge=lambda: "state failed")
        filtered = {
            "all_items": [item],
            "passed": [item],
            "dropped": [],
        }
        with patch("main.load_articles", return_value=[item]), patch(
            "main.run_filter_pipeline",
            return_value=filtered,
        ), patch(
            "main.enrich_items",
            return_value=[item],
        ), patch(
            "main.append_processed_items",
            return_value=Path("data/processed/x.jsonl"),
        ), patch(
            "main.render_platform_feed",
            return_value=Path("reports/x.html"),
        ):
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, main.EXIT_STATE)

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

        def notify(*args, **kwargs):
            events.append("notify")
            return False

        with patch("main.load_articles", return_value=[item]), patch(
            "main.run_filter_pipeline",
            return_value=filtered,
        ), patch(
            "main.enrich_items",
            return_value=[item],
        ), patch(
            "main.append_processed_items",
            return_value=Path("data/processed/x.jsonl"),
        ), patch(
            "main.render_platform_feed",
            return_value=Path("reports/x.html"),
        ), patch.object(
            main.config,
            "ENABLE_WECOM",
            True,
        ), patch(
            "notifier.wecom.send_to_wecom",
            side_effect=notify,
        ):
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, main.EXIT_NOTIFY)
        self.assertEqual(events, ["acknowledge", "notify"])


if __name__ == "__main__":
    unittest.main()
