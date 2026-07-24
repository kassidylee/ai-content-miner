"""Twitter 新流程的第三层回复区质量筛选。"""

from __future__ import annotations

import re
from numbers import Real
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import config
from analyzer.twitter_common import append_twitter_filter_stage


class TwitterCommentConfigError(ValueError):
    """Twitter 回复筛选配置错误。"""


def _number(
    settings: Dict[str, object],
    name: str,
    minimum: float,
    maximum: Optional[float] = None,
) -> float:
    value = settings.get(name)
    if not isinstance(value, Real):
        raise TwitterCommentConfigError(f"{name} 必须是数字")
    numeric = float(value)
    if numeric < minimum or (maximum is not None and numeric > maximum):
        raise TwitterCommentConfigError(f"{name} 超出允许范围")
    return numeric


def twitter_comment_settings() -> Dict[str, object]:
    configured = config.TWITTER_COMMENT_FILTER
    if not isinstance(configured, dict):
        raise TwitterCommentConfigError(
            "TWITTER_COMMENT_FILTER 必须是字典"
        )
    settings = dict(configured)
    integer_fields = (
        "max_replies",
        "min_sample_size",
        "min_critical_authors",
        "strong_critical_authors",
        "strong_critical_min_likes",
    )
    for name in integer_fields:
        minimum = 0 if name == "strong_critical_min_likes" else 1
        settings[name] = int(_number(settings, name, minimum))
    settings["timeout_seconds"] = _number(
        settings,
        "timeout_seconds",
        0.1,
    )
    for name in (
        "critical_ratio_threshold",
        "weighted_ratio_threshold",
        "strong_weighted_ratio_threshold",
    ):
        settings[name] = _number(settings, name, 0, 1)

    keywords = settings.get("critical_keywords", [])
    suffixes = settings.get("ignored_username_suffixes", [])
    if not isinstance(keywords, list) or any(
        not isinstance(value, str) for value in keywords
    ):
        raise TwitterCommentConfigError(
            "critical_keywords 必须是字符串列表"
        )
    if not isinstance(suffixes, list) or any(
        not isinstance(value, str) for value in suffixes
    ):
        raise TwitterCommentConfigError(
            "ignored_username_suffixes 必须是字符串列表"
        )
    settings["critical_keywords"] = [
        value.casefold().strip() for value in keywords if value.strip()
    ]
    settings["ignored_username_suffixes"] = [
        value.casefold().strip() for value in suffixes if value.strip()
    ]
    return settings


def _stage(
    decision: str,
    reason_code: str,
    details: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    return {
        "stage": "comments",
        "decision": decision,
        "reason_codes": [reason_code],
        "details": details or {},
    }


def _like_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _effective_replies(
    item: Dict,
    replies: Sequence[Dict[str, object]],
    ignored_suffixes: Sequence[str],
) -> List[Dict[str, object]]:
    original_username = str(item.get("username", "") or "").casefold()
    seen_contents = set()
    seen_authors = set()
    effective: List[Dict[str, object]] = []
    ordered = sorted(
        replies,
        key=lambda reply: _like_count(reply.get("like_count"))
        if isinstance(reply, dict)
        else 0,
        reverse=True,
    )
    for index, reply in enumerate(ordered):
        if not isinstance(reply, dict):
            continue
        content = re.sub(
            r"\s+",
            " ",
            str(reply.get("content", "") or ""),
        ).strip()
        if not content:
            continue
        normalized_content = content.casefold()
        username = str(
            reply.get("author_username", "") or ""
        ).casefold().strip()
        if normalized_content in seen_contents:
            continue
        if reply.get("is_original_author") or (
            username and username == original_username
        ):
            continue
        if username and any(
            username.endswith(suffix) for suffix in ignored_suffixes
        ):
            continue
        author_key = username or f"__unknown_{index}"
        if username and author_key in seen_authors:
            continue
        seen_contents.add(normalized_content)
        seen_authors.add(author_key)
        effective.append(
            {
                "id": str(reply.get("id", "") or ""),
                "content": content,
                "author_username": username,
                "like_count": _like_count(reply.get("like_count")),
            }
        )
    return effective


def evaluate_twitter_replies(
    item: Dict,
    fetch_result: Dict[str, object],
    settings: Dict[str, object],
) -> Dict[str, object]:
    if not fetch_result.get("available"):
        return _stage(
            "skip",
            "TWITTER_REPLIES_UNAVAILABLE",
            {"error": str(fetch_result.get("error", "") or "")[:160]},
        )
    raw_replies = fetch_result.get("comments", [])
    if not isinstance(raw_replies, list):
        raw_replies = []
    sampled = sorted(
        raw_replies,
        key=lambda reply: _like_count(reply.get("like_count"))
        if isinstance(reply, dict)
        else 0,
        reverse=True,
    )[: int(settings["max_replies"])]
    replies = _effective_replies(
        item,
        sampled,
        settings["ignored_username_suffixes"],
    )
    if not replies:
        return _stage(
            "pass",
            "TWITTER_REPLIES_EMPTY",
            {"sample_size": 0, "confidence": "low"},
        )

    keywords = settings["critical_keywords"]
    critical: List[Dict[str, object]] = []
    matched_keywords = set()
    total_weight = 0
    critical_weight = 0
    for reply in replies:
        weight = max(1, min(_like_count(reply.get("like_count")), 50))
        total_weight += weight
        text = str(reply.get("content", "") or "").casefold()
        hits = [keyword for keyword in keywords if keyword in text]
        if hits:
            critical.append(reply)
            critical_weight += weight
            matched_keywords.update(hits)

    critical_authors = {
        str(reply.get("author_username", "") or "")
        for reply in critical
        if str(reply.get("author_username", "") or "")
    }
    strong_authors = {
        str(reply.get("author_username", "") or "")
        for reply in critical
        if str(reply.get("author_username", "") or "")
        and _like_count(reply.get("like_count"))
        >= int(settings["strong_critical_min_likes"])
    }
    sample_size = len(replies)
    critical_ratio = len(critical) / sample_size
    weighted_ratio = critical_weight / total_weight if total_weight else 0.0
    details = {
        "sample_size": sample_size,
        "critical_count": len(critical),
        "critical_author_count": len(critical_authors),
        "strong_critical_author_count": len(strong_authors),
        "critical_ratio": round(critical_ratio, 4),
        "weighted_critical_ratio": round(weighted_ratio, 4),
        "matched_keywords": sorted(matched_keywords),
        "confidence": "low"
        if sample_size < int(settings["min_sample_size"])
        else "high",
    }
    if sample_size < int(settings["min_sample_size"]):
        return _stage("pass", "TWITTER_REPLIES_LOW_SAMPLE", details)

    primary = (
        len(critical_authors) >= int(settings["min_critical_authors"])
        and critical_ratio >= float(settings["critical_ratio_threshold"])
        and weighted_ratio >= float(settings["weighted_ratio_threshold"])
    )
    strong = (
        len(strong_authors) >= int(settings["strong_critical_authors"])
        and weighted_ratio
        >= float(settings["strong_weighted_ratio_threshold"])
    )
    if primary or strong:
        details["matched_rule"] = "primary" if primary else "strong_evidence"
        return _stage(
            "drop",
            "TWITTER_REPLIES_STRONG_CHALLENGE",
            details,
        )
    return _stage("pass", "TWITTER_REPLIES_PASSED", details)


def apply_twitter_comment_filter(
    items: Iterable[Dict],
    reply_provider: Optional[object],
) -> Tuple[List[Dict], List[Dict]]:
    """获取并筛选回复；接口失败时保留内容并记录原因。"""
    candidates = list(items)
    if not candidates:
        return [], []
    settings = twitter_comment_settings()
    if not settings.get("enabled") or reply_provider is None:
        fetched: Dict[str, Dict[str, object]] = {}
    else:
        try:
            fetched = reply_provider.fetch_replies(
                candidates,
                limit=int(settings["max_replies"]),
                timeout_seconds=float(settings["timeout_seconds"]),
            )
        except Exception:
            fetched = {}

    passed: List[Dict] = []
    dropped: List[Dict] = []
    for item in candidates:
        result = evaluate_twitter_replies(
            item,
            fetched.get(
                str(item.get("id", "") or ""),
                {
                    "available": False,
                    "comments": [],
                    "error": "Twitter 回复提供能力不可用",
                },
            ),
            settings,
        )
        append_twitter_filter_stage(item, result)
        (dropped if result["decision"] == "drop" else passed).append(item)
    return passed, dropped
