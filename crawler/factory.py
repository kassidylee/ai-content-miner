"""根据目标平台选择真正可用的采集器。"""

from __future__ import annotations

import config
from crawler.base import CollectorBridge
from crawler.mediacrawler_bridge import MediaCrawlerBridge
from crawler.reddit_bridge import RedditBridge
from crawler.twscrape_bridge import TwscrapeBridge


def build_collector() -> CollectorBridge:
    """为当前配置构造采集器；X 和 Reddit 不经过 MediaCrawler。"""
    platform = str(getattr(config, "CRAWL_PLATFORM", "")).strip().lower()
    if platform in {"x", "twitter", "x.com"}:
        return TwscrapeBridge()
    if platform == "reddit":
        return RedditBridge()
    return MediaCrawlerBridge()
