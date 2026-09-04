"""根据目标平台选择真正可用的采集器。"""

from __future__ import annotations

import config
from crawler.base import CollectorBridge
from crawler.github_bridge import GithubBridge
from crawler.mediacrawler_bridge import MediaCrawlerBridge
from crawler.reddit_rss_bridge import RedditRssBridge
from crawler.twscrape_bridge import TwscrapeBridge
from crawler.youtube_bridge import YoutubeBridge


def build_collector() -> CollectorBridge:
    """为当前配置构造采集器；每个平台使用独立桥接器。"""
    platform = str(getattr(config, "CRAWL_PLATFORM", "")).strip().lower()
    if platform in {"x", "twitter", "x.com"}:
        return TwscrapeBridge()
    if platform in {"github", "gh"}:
        return GithubBridge()
    if platform == "reddit":
        return RedditRssBridge()
    if platform in {"youtube", "yt", "ytb"}:
        return YoutubeBridge()
    return MediaCrawlerBridge()
