"""Reddit 专用筛选的第一层本地内容与来源规则。"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

import config
from analyzer.reddit_common import (
    append_reddit_filter_stage,
    raw_reddit_record,
)


SUBREDDIT_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
REDDIT_HOSTS = {"reddit.com", "www.reddit.com", "old.reddit.com"}


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _valid_reddit_url(value: object) -> bool:
    parsed = urlparse(_clean(value))
    parts = [part for part in parsed.path.split("/") if part]
    return (
        parsed.scheme == "https"
        and parsed.netloc.casefold() in REDDIT_HOSTS
        and len(parts) >= 5
        and parts[0].casefold() == "r"
        and parts[2].casefold() == "comments"
    )


def _result(
    decision: str,
    reason_code: str,
    details: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    return {
        "stage": "rules",
        "decision": decision,
        "reason_codes": [reason_code],
        "details": details or {},
    }


def validate_reddit_rule_config() -> None:
    rules = getattr(config, "REDDIT_RULE_FILTER", None)
    if not isinstance(rules, dict):
        raise ValueError("REDDIT_RULE_FILTER 必须是字典")
    minimum = rules.get("min_content_chars")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise ValueError("REDDIT_RULE_FILTER.min_content_chars 必须是正整数")
    values = rules.get("exclude_keywords", [])
    if not isinstance(values, list) or any(
        not isinstance(value, str) for value in values
    ):
        raise ValueError(
            "REDDIT_RULE_FILTER.exclude_keywords 必须是字符串列表"
        )


def evaluate_reddit_rules(
    item: Dict,
    seen_ids: Set[str],
    seen_urls: Set[str],
) -> Dict[str, object]:
    """校验 Reddit RSS 记录并执行批次内去重，不调用外部服务。"""
    rules = config.REDDIT_RULE_FILTER
    raw = raw_reddit_record(item)
    source = _clean(item.get("source")).casefold()
    post_id = _clean(raw.get("id"))
    post_url = _clean(item.get("url"))
    normalized_url = post_url.casefold().rstrip("/")
    subreddit = _clean(
        raw.get("subreddit") or raw.get("search_subreddit")
    )
    collection_method = _clean(raw.get("collection_method")).casefold()

    if source != "reddit":
        return _result("drop", "REDDIT_RULE_WRONG_PLATFORM")
    if collection_method != "reddit_rss":
        return _result("drop", "REDDIT_RULE_UNSUPPORTED_COLLECTION_METHOD")
    if not post_id:
        return _result("drop", "REDDIT_RULE_MISSING_ID")
    if not _valid_reddit_url(post_url):
        return _result("drop", "REDDIT_RULE_INVALID_POST_URL")
    if not subreddit or not SUBREDDIT_PATTERN.fullmatch(subreddit):
        return _result("drop", "REDDIT_RULE_INVALID_SUBREDDIT")
    if post_id in seen_ids:
        return _result("drop", "REDDIT_RULE_DUPLICATE_ID")
    if normalized_url in seen_urls:
        return _result("drop", "REDDIT_RULE_DUPLICATE_URL")

    title = _clean(item.get("title"))
    content = _clean(item.get("content"))
    searchable = f"{title}\n{content}".casefold()
    for keyword in rules.get("exclude_keywords", []):
        normalized_keyword = keyword.strip().casefold()
        if normalized_keyword and normalized_keyword in searchable:
            return _result(
                "drop",
                "REDDIT_RULE_EXCLUDED_KEYWORD",
                {"keyword": keyword},
            )

    meaningful_chars = len("".join(f"{title}{content}".split()))
    minimum = int(rules["min_content_chars"])
    if meaningful_chars < minimum:
        return _result(
            "drop",
            "REDDIT_RULE_CONTENT_TOO_SHORT",
            {"meaningful_chars": meaningful_chars, "minimum": minimum},
        )

    seen_ids.add(post_id)
    seen_urls.add(normalized_url)
    return _result(
        "pass",
        "REDDIT_RULES_PASSED",
        {
            "post_id": post_id,
            "subreddit": subreddit,
            "meaningful_chars": meaningful_chars,
            "metrics_available": raw.get("metrics_available") is True,
        },
    )


def apply_reddit_rules(
    items: Iterable[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """批量执行 Reddit 第一层规则。"""
    validate_reddit_rule_config()
    passed: List[Dict] = []
    dropped: List[Dict] = []
    seen_ids: Set[str] = set()
    seen_urls: Set[str] = set()
    for item in items:
        result = evaluate_reddit_rules(item, seen_ids, seen_urls)
        append_reddit_filter_stage(item, result)
        (passed if result["decision"] == "pass" else dropped).append(item)
    return passed, dropped
