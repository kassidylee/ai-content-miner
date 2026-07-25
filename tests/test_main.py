import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from analyzer.filter import FilterResult
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

    def test_runtime_config_rejects_invalid_score_threshold(self):
        bridge = SimpleNamespace(validate=lambda: [])
        with patch.object(main.config, "API_KEY", "test-key"), patch.object(
            main.config, "WECOM_WEBHOOK", "https://example.org/hook"
        ), patch.object(
            main.config, "SCORE_THRESHOLD", 11
        ):
            errors = main.validate_runtime_config(bridge)

        self.assertIn(
            "SCORE_THRESHOLD 必须是 0 到 10 之间的数字",
            errors,
        )

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
            "main.multi_stage_filter",
            return_value=FilterResult(),
        ), patch(
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
        ) as non_twitter_loader:
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, 0)
        twitter_workflow.assert_called_once_with(bridge)
        non_twitter_loader.assert_not_called()

    def test_xhs_and_zhihu_use_four_stage_workflow(self):
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
                    return_value=[{"title": "four-stage item"}],
                ) as article_loader, patch(
                    "main.multi_stage_filter",
                    return_value=FilterResult(),
                ) as four_stage_filter, patch(
                    "main.generate_reports",
                    return_value=([], 0),
                ) as report_generator:
                    exit_code = main.run_workflow(bridge)

                self.assertEqual(exit_code, main.EXIT_OK)
                twitter_workflow.assert_not_called()
                article_loader.assert_called_once_with(
                    ("current.jsonl",),
                    platform=platform,
                    allow_manual_fallback=False,
                )
                four_stage_filter.assert_called_once_with(
                    {"title": "four-stage item"},
                    existing_articles=None,
                    enable_semantic=True,
                    enable_comment=True,
                    enable_author_profile=True,
                )
                report_generator.assert_called_once()

    def test_generate_reports_uses_normalized_zero_to_ten_threshold(self):
        below_threshold = {
            "article": {"title": "低于阈值"},
            "total_score": 5.99,
        }
        at_threshold = {
            "article": {"title": "达到阈值"},
            "total_score": 6.0,
        }

        with patch.object(main.config, "SCORE_THRESHOLD", 6.0), patch(
            "output.generator.generate_output",
            return_value="/tmp/report.txt",
        ) as generate_output, patch(
            "utils.raditer.log_decision"
        ) as log_decision, patch(
            "main.time.sleep"
        ):
            final_items, generated_count = main.generate_reports(
                [below_threshold, at_threshold]
            )

        self.assertEqual(final_items, [at_threshold])
        self.assertEqual(generated_count, 1)
        generate_output.assert_called_once_with(at_threshold)
        log_decision.assert_called_once_with(
            at_threshold,
            "/tmp/report.txt",
        )


if __name__ == "__main__":
    unittest.main()
