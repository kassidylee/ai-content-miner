import unittest
from unittest.mock import patch

import main
from crawler.base import CrawlRunResult


class MainGithubTest(unittest.TestCase):
    def test_github_uses_dedicated_filter(self):
        bridge = type("Bridge", (), {
            "platform": "github",
            "run": lambda self: CrawlRunResult(success=True, data_files=("github.jsonl",)),
            "acknowledge": lambda self: "",
        })()
        with patch("main.load_articles", return_value=[{"title": "repo"}]), patch(
            "main._run_github_filters", return_value=([], 1)
        ) as github_filter, patch("main.generate_reports", return_value=([], 0)), patch(
            "main.multi_stage_filter"
        ) as legacy_filter:
            code = main.run_workflow(bridge)
        self.assertEqual(code, main.EXIT_OK)
        github_filter.assert_called_once()
        legacy_filter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
