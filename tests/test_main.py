import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from crawler.base import CrawlRunResult


class MainTest(unittest.TestCase):
    def test_runtime_config_includes_application_and_crawler_errors(self):
        bridge = SimpleNamespace(validate=lambda: ["crawler-error"])
        with patch.object(main.config, "API_KEY", "your-api-key-here"), patch.object(
            main.config, "WECOM_WEBHOOK", "https://example.com/hook"
        ):
            errors = main.validate_runtime_config(bridge)

        self.assertTrue(any("API_KEY" in error for error in errors))
        self.assertTrue(any("WECOM_WEBHOOK" in error for error in errors))
        self.assertIn("crawler-error", errors)

    def test_crawler_failure_returns_nonzero_and_stops_pipeline(self):
        bridge = SimpleNamespace(
            platform="xhs",
            run=lambda: CrawlRunResult(success=False, error="crawler failed"),
        )
        with patch("main.load_articles") as article_loader:
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, main.EXIT_CRAWLER)
        article_loader.assert_not_called()

    def test_empty_current_run_returns_nonzero(self):
        bridge = SimpleNamespace(
            platform="zhihu",
            run=lambda: CrawlRunResult(success=True, data_files=("current.jsonl",)),
        )
        with patch("main.load_articles", return_value=[]):
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, main.EXIT_NO_DATA)

    def test_state_failure_after_processing_returns_nonzero(self):
        bridge = SimpleNamespace(
            platform="xhs",
            run=lambda: CrawlRunResult(success=True, data_files=("current.jsonl",)),
            acknowledge=lambda: "state failed",
        )
        with patch("main.load_articles", return_value=[{"title": "test"}]), patch(
            "main.analyze_articles"
        ), patch("main.score_articles", return_value=([], 1)), patch(
            "main.generate_reports", return_value=([], 0)
        ):
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, main.EXIT_STATE)

    def test_x_routes_to_twitter_workflow_without_legacy_steps(self):
        bridge = SimpleNamespace(platform="x")
        with patch(
            "workflows.twitter.run_twitter_workflow",
            return_value=0,
        ) as twitter_workflow, patch(
            "main.load_articles"
        ) as legacy_loader, patch(
            "main.analyze_articles"
        ) as legacy_analyzer:
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, 0)
        twitter_workflow.assert_called_once_with(bridge)
        legacy_loader.assert_not_called()
        legacy_analyzer.assert_not_called()

    def test_xhs_and_zhihu_keep_using_legacy_workflow(self):
        for platform in ("xhs", "zhihu"):
            with self.subTest(platform=platform):
                bridge = SimpleNamespace(
                    platform=platform,
                    run=lambda: CrawlRunResult(
                        success=True,
                        data_files=("current.jsonl",),
                    ),
                    acknowledge=lambda: "",
                )
                with patch(
                    "workflows.twitter.run_twitter_workflow"
                ) as twitter_workflow, patch(
                    "main.load_articles",
                    return_value=[{"title": "legacy item"}],
                ) as legacy_loader, patch(
                    "main.analyze_articles"
                ) as legacy_analyzer, patch(
                    "main.score_articles",
                    return_value=([], 0),
                ) as legacy_scorer, patch(
                    "main.generate_reports",
                    return_value=([], 0),
                ) as legacy_generator:
                    exit_code = main.run_workflow(bridge)

                self.assertEqual(exit_code, main.EXIT_OK)
                twitter_workflow.assert_not_called()
                legacy_loader.assert_called_once_with(
                    ("current.jsonl",),
                    platform=platform,
                    allow_manual_fallback=False,
                )
                legacy_analyzer.assert_called_once()
                legacy_scorer.assert_called_once()
                legacy_generator.assert_called_once()


if __name__ == "__main__":
    unittest.main()
