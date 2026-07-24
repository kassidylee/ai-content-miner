"""第一层规则筛选。

模块只依赖统一内容字段，平台差异全部来自 ``config.PLATFORM_FILTERS``。
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

import config


URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"(?<!\w)@\w+")
DECORATION_PATTERN = re.compile(r"[^\w\u4e00-\u9fff#]+", re.UNICODE)


def _stage_result(
    decision: str,
    reason_codes: List[str],
    details: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    return {
        "stage": "rules",
        "decision": decision,
        "reason_codes": reason_codes,
        "details": details or {},
    }


def append_filter_stage(item: Dict, result: Dict[str, object]) -> None:
    """把阶段结果写入统一筛选元数据。"""
    metadata = item.setdefault(
        "filter_metadata",
        {"stages": [], "final_decision": "pending", "final_reason_codes": []},
    )
    metadata.setdefault("stages", []).append(result)
    if result["decision"] == "drop":
        metadata["final_decision"] = "drop"
        metadata["final_reason_codes"] = list(result.get("reason_codes", []))


def get_platform_filter_config(platform: str) -> Dict[str, object]:
    """合并默认规则和平台覆盖项。"""
    all_configs = getattr(config, "PLATFORM_FILTERS", {})
    default_config = dict(all_configs.get("default", {}))
    default_config.update(all_configs.get(platform, {}))
    return default_config


def build_meaningful_text(item: Dict) -> str:
    """移除链接、用户名和装饰字符，保留可判断的信息文本。"""
    content = str(item.get("content", "") or "")
    content = URL_PATTERN.sub(" ", content)
    content = MENTION_PATTERN.sub(" ", content)
    content = DECORATION_PATTERN.sub(" ", content)
    return re.sub(r"\s+", " ", content).strip()


def _valid_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _duplicate_key(item: Dict) -> str:
    text = build_meaningful_text(item).casefold()
    return re.sub(r"\s+", " ", text)


def _first_external_url(item: Dict) -> str:
    for entry in item.get("referenced_urls", []):
        if isinstance(entry, dict) and _valid_http_url(entry.get("url")):
            return str(entry["url"]).strip().casefold()
    return ""


def evaluate_rule_filter(
    item: Dict,
    seen_texts: Optional[Set[str]] = None,
    seen_urls: Optional[Set[str]] = None,
) -> Dict[str, object]:
    """评估单条内容，不调用外部服务。"""
    platform = str(item.get("platform", "unknown") or "unknown")
    rules = get_platform_filter_config(platform)
    platform_metadata = item.get("platform_metadata", {})
    if not isinstance(platform_metadata, dict):
        platform_metadata = {}

    if rules.get("require_platform_id") and not item.get("platform_item_id"):
        return _stage_result("drop", ["RULE_MISSING_PLATFORM_ID"])
    if not str(item.get("content", "") or "").strip():
        return _stage_result("drop", ["RULE_EMPTY_CONTENT"])
    if not _valid_http_url(item.get("source_url")):
        return _stage_result("drop", ["RULE_INVALID_SOURCE_URL"])
    if item.get("published_at") is None:
        return _stage_result("drop", ["RULE_MISSING_PUBLISHED_AT"])

    if rules.get("drop_sensitive") and platform_metadata.get(
        "possibly_sensitive"
    ):
        return _stage_result("drop", ["RULE_SENSITIVE_CONTENT"])
    if not rules.get("allow_replies", True) and platform_metadata.get("is_reply"):
        return _stage_result("drop", ["RULE_REPLY_NOT_ALLOWED"])
    if not rules.get("allow_retweets", True) and platform_metadata.get(
        "is_retweet"
    ):
        return _stage_result("drop", ["RULE_RETWEET_NOT_ALLOWED"])
    if not rules.get("allow_quotes", True) and platform_metadata.get("is_quote"):
        return _stage_result("drop", ["RULE_QUOTE_NOT_ALLOWED"])

    language = str(platform_metadata.get("lang", "") or "").lower()
    allowed_languages = {
        str(value).lower() for value in rules.get("allowed_languages", [])
    }
    if allowed_languages and language and language not in allowed_languages:
        return _stage_result(
            "drop",
            ["RULE_LANGUAGE_NOT_ALLOWED"],
            {"language": language},
        )

    searchable_text = " ".join(
        [
            str(item.get("title", "") or ""),
            str(item.get("content", "") or ""),
        ]
    ).casefold()
    for keyword in rules.get("exclude_keywords", []):
        normalized_keyword = str(keyword).strip().casefold()
        if normalized_keyword and normalized_keyword in searchable_text:
            return _stage_result(
                "drop",
                ["RULE_EXCLUDED_KEYWORD"],
                {"keyword": str(keyword)},
            )

    meaningful_text = build_meaningful_text(item)
    minimum = int(rules.get("min_meaningful_chars", 1) or 1)
    if len(meaningful_text) < minimum and not item.get("referenced_urls"):
        return _stage_result(
            "drop",
            ["RULE_CONTENT_TOO_SHORT"],
            {"meaningful_chars": len(meaningful_text), "minimum": minimum},
        )

    text_key = _duplicate_key(item)
    if seen_texts is not None and text_key and text_key in seen_texts:
        return _stage_result("drop", ["RULE_DUPLICATE_CONTENT"])

    external_url = _first_external_url(item)
    if seen_urls is not None and external_url and external_url in seen_urls:
        return _stage_result(
            "drop",
            ["RULE_DUPLICATE_EXTERNAL_URL"],
            {"url": external_url},
        )

    if seen_texts is not None and text_key:
        seen_texts.add(text_key)
    if seen_urls is not None and external_url:
        seen_urls.add(external_url)

    return _stage_result(
        "pass",
        ["RULES_PASSED"],
        {
            "language": language,
            "meaningful_chars": len(meaningful_text),
            "is_reply": bool(platform_metadata.get("is_reply")),
            "is_retweet": bool(platform_metadata.get("is_retweet")),
        },
    )


def apply_rule_filters(items: Iterable[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """批量执行第一层规则，返回通过项和删除项。"""
    passed: List[Dict] = []
    dropped: List[Dict] = []
    seen_texts: Set[str] = set()
    seen_urls: Set[str] = set()

    for item in items:
        result = evaluate_rule_filter(item, seen_texts, seen_urls)
        append_filter_stage(item, result)
        if result["decision"] == "pass":
            passed.append(item)
        else:
            dropped.append(item)
    return passed, dropped


def rule_filter(article: Dict) -> Tuple[bool, str]:
    """兼容旧主流程的单条规则接口。"""
    result = evaluate_rule_filter(article)
    append_filter_stage(article, result)
    passed = result["decision"] == "pass"
    reason = ",".join(result["reason_codes"])
    return passed, reason


def get_blogger_weight(_article: Dict) -> float:
    """旧评分流程的临时兼容接口；新流程不使用作者权重。"""
    return 1.0
