import unittest
from unittest.mock import patch

from crawler import factory


class CollectorFactoryTest(unittest.TestCase):
    def test_x_uses_twikit_instead_of_mediacrawler(self):
        collector = object()
        with patch.object(factory.config, "CRAWL_PLATFORM", "x"), patch.object(
            factory, "TwikitBridge", return_value=collector
        ) as twikit_bridge, patch.object(factory, "MediaCrawlerBridge") as media_bridge:
            result = factory.build_collector()

        self.assertIs(result, collector)
        twikit_bridge.assert_called_once_with()
        media_bridge.assert_not_called()

    def test_xhs_keeps_using_mediacrawler(self):
        collector = object()
        with patch.object(factory.config, "CRAWL_PLATFORM", "xhs"), patch.object(
            factory, "MediaCrawlerBridge", return_value=collector
        ) as media_bridge, patch.object(factory, "TwikitBridge") as twikit_bridge:
            result = factory.build_collector()

        self.assertIs(result, collector)
        media_bridge.assert_called_once_with()
        twikit_bridge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
