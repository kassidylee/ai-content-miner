import unittest
from unittest.mock import patch

from crawler.factory import build_collector
from crawler.mediacrawler_bridge import MediaCrawlerBridge
from crawler.reddit_bridge import RedditBridge
from crawler.twscrape_bridge import TwscrapeBridge


class CollectorFactoryTest(unittest.TestCase):
    def test_x_uses_twscrape_instead_of_mediacrawler(self):
        with patch("crawler.factory.config.CRAWL_PLATFORM", "x"):
            collector = build_collector()

        self.assertIsInstance(collector, TwscrapeBridge)

    def test_xhs_keeps_using_mediacrawler(self):
        with patch("crawler.factory.config.CRAWL_PLATFORM", "xhs"):
            collector = build_collector()

        self.assertIsInstance(collector, MediaCrawlerBridge)

    def test_reddit_uses_praw_instead_of_mediacrawler(self):
        with patch("crawler.factory.config.CRAWL_PLATFORM", "reddit"):
            collector = build_collector()

        self.assertIsInstance(collector, RedditBridge)


if __name__ == "__main__":
    unittest.main()
