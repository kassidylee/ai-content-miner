"""Twitter 新流程的第一层规则筛选。"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Set, Tuple
from urllib.parse import urlparse

import config
from analyzer.twitter_common import append_twitter_filter_stage


URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"(?<!\w)@\w+")
DECORATION_PATTERN = re.compile(r"[^\w\u4e00-\u9fff#]+", re.UNICODE)


def meaningful_twitter_text(item: Dict) -> str:
    """移除链接、用户名和装饰字符，保留有效正文。"""
    content = str(item.get("content", "") or "")
    content = URL_PATTERN.sub(" ", content)
    content = MENTION_PATTERN.sub(" ", content)
    content = DECORATION_PATTERN.sub(" ", content)
    return re.sub(r"\s+", " ", content).strip()


def _valid_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _first_external_url(item: Dict) -> str:
    for entry in item.get("referenced_urls", []):
        if isinstance(entry, dict) and _valid_http_url(entry.get("url")):
            return str(entry["url"]).strip().casefold()
    return ""


def _result(
    decision: str,
    reason_code: str,
    details: Dict[str, object] | None = None,
) -> Dict[str, object]:
    return {
        "stage": "rules",
        "decision": decision,
        "reason_codes": [reason_code],
        "details": details or {},
    }


def validate_twitter_rule_config() -> None:
    rules = config.TWITTER_RULE_FILTER
    if not isinstance(rules, dict):
        raise ValueError("TWITTER_RULE_FILTER 必须是字典")
    minimum = rules.get("min_meaningful_chars")
    if not isinstance(minimum, int) or minimum < 1:
        raise ValueError(
            "TWITTER_RULE_FILTER.min_meaningful_chars 必须是正整数"
        )
    for name in ("allowed_languages", "exclude_keywords"):
        values = rules.get(name, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) for value in values
        ):
            raise ValueError(f"TWITTER_RULE_FILTER.{name} 必须是字符串列表")


def evaluate_twitter_rules(
    item: Dict,
    seen_texts: Set[str],
    seen_urls: Set[str],
) -> Dict[str, object]:
    """评估单条 Twitter 内容，不调用外部服务。"""
    rules = config.TWITTER_RULE_FILTER
    metadata = item.get("platform_metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    if item.get("platform") != "x":
        return _result("drop", "TWITTER_RULE_WRONG_PLATFORM")
    if not item.get("platform_item_id"):
        return _result("drop", "TWITTER_RULE_MISSING_ID")
    if not str(item.get("content", "") or "").strip():
        return _result("drop", "TWITTER_RULE_EMPTY_CONTENT")
    if not _valid_http_url(item.get("source_url")):
        return _result("drop", "TWITTER_RULE_INVALID_SOURCE_URL")
    if item.get("published_at") is None:
        return _result("drop", "TWITTER_RULE_MISSING_PUBLISHED_AT")
    if rules.get("drop_sensitive") and metadata.get("possibly_sensitive"):
        return _result("drop", "TWITTER_RULE_SENSITIVE_CONTENT")
    if not rules.get("allow_replies", True) and metadata.get("is_reply"):
        return _result("drop", "TWITTER_RULE_REPLY_NOT_ALLOWED")
    if not rules.get("allow_retweets", True) and metadata.get("is_retweet"):
        return _result("drop", "TWITTER_RULE_RETWEET_NOT_ALLOWED")
    if not rules.get("allow_quotes", True) and metadata.get("is_quote"):
        return _result("drop", "TWITTER_RULE_QUOTE_NOT_ALLOWED")

    language = str(metadata.get("lang", "") or "").casefold()
    allowed = {
        str(value).casefold()
        for value in rules.get("allowed_languages", [])
    }
    if allowed and language and language not in allowed:
        return _result(
            "drop",
            "TWITTER_RULE_LANGUAGE_NOT_ALLOWED",
            {"language": language},
        )

    searchable = " ".join(
        [
            str(item.get("title", "") or ""),
            str(item.get("content", "") or ""),
        ]
    ).casefold()
    for keyword in rules.get("exclude_keywords", []):
        normalized = str(keyword).strip().casefold()
        if normalized and normalized in searchable:
            return _result(
                "drop",
                "TWITTER_RULE_EXCLUDED_KEYWORD",
                {"keyword": str(keyword)},
            )

    meaningful = meaningful_twitter_text(item)
    minimum = int(rules.get("min_meaningful_chars", 1) or 1)
    if len(meaningful) < minimum and not item.get("referenced_urls"):
        return _result(
            "drop",
            "TWITTER_RULE_CONTENT_TOO_SHORT",
            {"meaningful_chars": len(meaningful), "minimum": minimum},
        )

    text_key = meaningful.casefold()
    if text_key and text_key in seen_texts:
        return _result("drop", "TWITTER_RULE_DUPLICATE_CONTENT")
    external_url = _first_external_url(item)
    if external_url and external_url in seen_urls:
        return _result("drop", "TWITTER_RULE_DUPLICATE_EXTERNAL_URL")

    if text_key:
        seen_texts.add(text_key)
    if external_url:
        seen_urls.add(external_url)
    return _result(
        "pass",
        "TWITTER_RULES_PASSED",
        {
            "language": language,
            "meaningful_chars": len(meaningful),
        },
    )


def apply_twitter_rules(
    items: Iterable[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """批量执行 Twitter 第一层筛选。"""
    passed: List[Dict] = []
    dropped: List[Dict] = []
    seen_texts: Set[str] = set()
    seen_urls: Set[str] = set()
    for item in items:
        result = evaluate_twitter_rules(item, seen_texts, seen_urls)
        append_twitter_filter_stage(item, result)
        (passed if result["decision"] == "pass" else dropped).append(item)
    return passed, dropped
