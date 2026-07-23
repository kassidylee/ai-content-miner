import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from crawler.mediacrawler_bridge import CrawlRunResult


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


if __name__ == "__main__":
    unittest.main()
