import unittest
from unittest.mock import patch

from crawler.factory import build_collector
from crawler.github_bridge import GithubBridge
from crawler.mediacrawler_bridge import MediaCrawlerBridge
from crawler.twscrape_bridge import TwscrapeBridge


class CollectorFactoryTest(unittest.TestCase):
    def test_x_uses_twscrape_instead_of_mediacrawler(self):
        with patch("crawler.factory.config.CRAWL_PLATFORM", "x"):
            collector = build_collector()

        self.assertIsInstance(collector, TwscrapeBridge)

    def test_github_uses_rest_bridge(self):
        with patch("crawler.factory.config.CRAWL_PLATFORM", "github"):
            collector = build_collector()

        self.assertIsInstance(collector, GithubBridge)

    def test_xhs_keeps_using_mediacrawler(self):
        with patch("crawler.factory.config.CRAWL_PLATFORM", "xhs"):
            collector = build_collector()

        self.assertIsInstance(collector, MediaCrawlerBridge)


if __name__ == "__main__":
    unittest.main()
