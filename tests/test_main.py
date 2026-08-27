import unittest
from datetime import datetime
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

    def test_runtime_config_validates_reddit_pipeline(self):
        bridge = SimpleNamespace(
            platform="reddit",
            validate=lambda: [],
        )
        with patch(
            "workflows.reddit.validate_reddit_runtime_config",
            return_value=[],
        ) as validate:
            errors = main.validate_runtime_config(bridge)

        self.assertEqual(errors, [])
        validate.assert_called_once_with(bridge)

    def test_crawler_failure_returns_nonzero_and_stops_pipeline(self):
        bridge = SimpleNamespace(
            platform="xhs",
            run=lambda: CrawlRunResult(success=False, error="crawler failed"),
        )
        with patch("main.load_articles") as article_loader:
            self.assertEqual(main.run_workflow(bridge), main.EXIT_CRAWLER)
        article_loader.assert_not_called()

    def test_empty_current_run_returns_nonzero(self):
        bridge = SimpleNamespace(
            platform="zhihu",
            run=lambda: CrawlRunResult(success=True, data_files=("current.jsonl",)),
        )
        with patch("main.load_articles", return_value=[]):
            self.assertEqual(main.run_workflow(bridge), main.EXIT_NO_DATA)

    def test_x_routes_to_twitter_workflow(self):
        bridge = SimpleNamespace(platform="x")
        with patch("workflows.twitter.run_twitter_workflow", return_value=0) as run:
            self.assertEqual(main.run_workflow(bridge), 0)
        run.assert_called_once_with(bridge)

    def test_state_failure_after_processing_returns_nonzero(self):
        bridge = SimpleNamespace(
            platform="xhs",
            run=lambda: CrawlRunResult(success=True, data_files=("current.jsonl",)),
            acknowledge=lambda: "state failed",
        )
        article = {"title": "AI Agent", "publish_time": datetime.now()}
        stats = {
            "kept": 1,
            "dropped_old": 0,
            "dropped_missing_time": 0,
            "dropped_unrelated": 0,
            "truncated": 0,
        }
        with patch("main.load_articles", return_value=[article]), patch(
            "main.recent_keyword_filter", return_value=([article], stats)
        ), patch(
            "main.multi_stage_filter", return_value=FilterResult(passed=True)
        ), patch(
            "main.generate_reports", return_value=([], 0)
        ):
            self.assertEqual(main.run_workflow(bridge), main.EXIT_STATE)

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
                    "main.recent_keyword_filter",
                    return_value=([{"title": "four-stage item"}], {
                        "kept": 1,
                        "dropped_old": 0,
                        "dropped_missing_time": 0,
                        "dropped_unrelated": 0,
                        "truncated": 0,
                    }),
                ), patch(
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

    def test_reddit_routes_to_dedicated_pipeline(self):
        bridge = SimpleNamespace(platform="reddit")
        with patch(
            "workflows.reddit.run_reddit_workflow",
            return_value=0,
        ) as reddit_workflow, patch(
            "main.load_articles",
        ) as generic_loader, patch(
            "main.generate_reports",
        ) as generic_reports:
            exit_code = main.run_workflow(bridge)

        self.assertEqual(exit_code, main.EXIT_OK)
        reddit_workflow.assert_called_once_with(bridge)
        generic_loader.assert_not_called()
        generic_reports.assert_not_called()

    def test_generate_reports_uses_normalized_zero_to_ten_threshold(self):
        below_threshold = {
            "article": {"title": "低于阈值"},
            "total_score": 5.99,
        }
        at_threshold = {
            "article": {"title": "达到阈值"},
            "total_score": 6.0,
        }

        with patch.object(main.config, "SCORE_THRESHOLD", 6.0), patch.object(
            main.config, "API_KEY", "test-key"
        ), patch(
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

    def test_xhs_uses_recent_filter_before_legacy_scoring(self):
        bridge = SimpleNamespace(
            platform="xhs",
            run=lambda: CrawlRunResult(success=True, data_files=("current.jsonl",)),
            acknowledge=lambda: "",
        )
        article = {"title": "AI Agent", "publish_time": datetime.now()}
        stats = {"kept": 1, "dropped_old": 0, "dropped_missing_time": 0,
                 "dropped_unrelated": 0, "truncated": 0}
        with patch("main.load_articles", return_value=[article]), patch(
            "main.recent_keyword_filter", return_value=([article], stats)
        ) as recent_filter, patch(
            "main.multi_stage_filter", return_value=FilterResult(passed=False)
        ) as legacy_filter, patch("main.generate_reports", return_value=([], 0)):
            self.assertEqual(main.run_workflow(bridge), main.EXIT_OK)
        recent_filter.assert_called_once_with([article])
        legacy_filter.assert_called_once()



if __name__ == "__main__":
    unittest.main()
