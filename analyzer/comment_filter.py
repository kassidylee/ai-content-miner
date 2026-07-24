"""第三层评论区质量筛选。"""

from __future__ import annotations

import re
from numbers import Real
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import config
from analyzer.filter import append_filter_stage
from crawler.base import CommentFetchResult, CommentProvider


class CommentFilterConfigError(ValueError):
    """评论筛选配置错误。"""


def _platform_config(platform: str) -> Dict[str, object]:
    all_configs = getattr(config, "COMMENT_FILTERS", {})
    if not isinstance(all_configs, dict):
        raise CommentFilterConfigError("COMMENT_FILTERS 必须是字典")
    settings = dict(all_configs.get("default", {}))
    settings.update(all_configs.get(platform, {}))
    return settings


def _number(
    settings: Dict[str, object],
    name: str,
    *,
    minimum: float,
    maximum: Optional[float] = None,
) -> float:
    value = settings.get(name)
    if not isinstance(value, Real):
        raise CommentFilterConfigError(f"{name} 必须是数字")
    numeric = float(value)
    if numeric < minimum or (maximum is not None and numeric > maximum):
        raise CommentFilterConfigError(f"{name} 超出允许范围")
    return numeric


def _validated_settings(platform: str) -> Dict[str, object]:
    settings = _platform_config(platform)
    settings["max_comments"] = int(
        _number(settings, "max_comments", minimum=1)
    )
    settings["timeout_seconds"] = _number(
        settings, "timeout_seconds", minimum=0.1
    )
    settings["min_sample_size"] = int(
        _number(settings, "min_sample_size", minimum=1)
    )
    settings["min_critical_authors"] = int(
        _number(settings, "min_critical_authors", minimum=1)
    )
    settings["critical_ratio_threshold"] = _number(
        settings,
        "critical_ratio_threshold",
        minimum=0,
        maximum=1,
    )
    settings["weighted_ratio_threshold"] = _number(
        settings,
        "weighted_ratio_threshold",
        minimum=0,
        maximum=1,
    )
    settings["strong_critical_authors"] = int(
        _number(settings, "strong_critical_authors", minimum=1)
    )
    settings["strong_critical_min_likes"] = int(
        _number(settings, "strong_critical_min_likes", minimum=0)
    )
    settings["strong_weighted_ratio_threshold"] = _number(
        settings,
        "strong_weighted_ratio_threshold",
        minimum=0,
        maximum=1,
    )

    keywords = settings.get("critical_keywords", [])
    suffixes = settings.get("ignored_username_suffixes", [])
    if not isinstance(keywords, list) or any(
        not isinstance(keyword, str) for keyword in keywords
    ):
        raise CommentFilterConfigError("critical_keywords 必须是字符串列表")
    if not isinstance(suffixes, list) or any(
        not isinstance(suffix, str) for suffix in suffixes
    ):
        raise CommentFilterConfigError(
            "ignored_username_suffixes 必须是字符串列表"
        )
    settings["critical_keywords"] = [
        keyword.casefold().strip() for keyword in keywords if keyword.strip()
    ]
    settings["ignored_username_suffixes"] = [
        suffix.casefold().strip() for suffix in suffixes if suffix.strip()
    ]
    return settings


def _stage_result(
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


def _safe_like_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_content(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _effective_comments(
    item: Dict,
    comments: Sequence[Dict[str, object]],
    ignored_suffixes: Sequence[str],
) -> List[Dict[str, object]]:
    """去除作者补充、机器人、重复内容和同一账号的重复回复。"""
    original_username = str(item.get("username", "") or "").casefold().strip()
    seen_contents = set()
    seen_authors = set()
    effective: List[Dict[str, object]] = []

    ordered = sorted(
        comments,
        key=lambda comment: _safe_like_count(comment.get("like_count")),
        reverse=True,
    )
    for index, comment in enumerate(ordered):
        if not isinstance(comment, dict):
            continue
        content = _normalize_content(comment.get("content"))
        if not content:
            continue
        normalized_content = content.casefold()
        if normalized_content in seen_contents:
            continue

        username = str(
            comment.get("author_username", "") or ""
        ).casefold().strip()
        is_original_author = bool(comment.get("is_original_author"))
        if original_username and username == original_username:
            is_original_author = True
        if is_original_author:
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
                "id": str(comment.get("id", "") or ""),
                "content": content,
                "author_username": username,
                "like_count": _safe_like_count(comment.get("like_count")),
            }
        )
    return effective


def evaluate_comments(
    item: Dict,
    fetch_result: CommentFetchResult,
    settings: Dict[str, object],
) -> Dict[str, object]:
    """根据标准化评论计算质疑比例和删除条件。"""
    if not fetch_result.available:
        return _stage_result(
            "skip",
            "REPLIES_UNAVAILABLE",
            {"error": str(fetch_result.error or "")[:160]},
        )

    comments = _effective_comments(
        item,
        list(fetch_result.comments)[: int(settings["max_comments"])],
        settings["ignored_username_suffixes"],
    )
    if not comments:
        return _stage_result(
            "pass",
            "REPLIES_EMPTY",
            {
                "sample_size": 0,
                "confidence": "low",
            },
        )

    keywords = settings["critical_keywords"]
    critical_comments: List[Dict[str, object]] = []
    matched_keywords = set()
    total_weight = 0
    critical_weight = 0
    for comment in comments:
        like_count = _safe_like_count(comment.get("like_count"))
        weight = max(1, min(like_count, 50))
        total_weight += weight
        text = str(comment.get("content", "") or "").casefold()
        hits = [keyword for keyword in keywords if keyword in text]
        if not hits:
            continue
        critical_comments.append(comment)
        critical_weight += weight
        matched_keywords.update(hits)

    critical_authors = {
        str(comment.get("author_username", "") or "")
        for comment in critical_comments
        if str(comment.get("author_username", "") or "")
    }
    strong_critical_authors = {
        str(comment.get("author_username", "") or "")
        for comment in critical_comments
        if str(comment.get("author_username", "") or "")
        and _safe_like_count(comment.get("like_count"))
        >= int(settings["strong_critical_min_likes"])
    }
    sample_size = len(comments)
    critical_ratio = len(critical_comments) / sample_size
    weighted_ratio = critical_weight / total_weight if total_weight else 0.0

    details = {
        "sample_size": sample_size,
        "critical_count": len(critical_comments),
        "critical_author_count": len(critical_authors),
        "strong_critical_author_count": len(strong_critical_authors),
        "critical_ratio": round(critical_ratio, 4),
        "weighted_critical_ratio": round(weighted_ratio, 4),
        "matched_keywords": sorted(matched_keywords),
        "confidence": "low"
        if sample_size < int(settings["min_sample_size"])
        else "high",
    }
    if sample_size < int(settings["min_sample_size"]):
        return _stage_result("pass", "REPLIES_LOW_SAMPLE", details)

    primary_drop = (
        len(critical_authors) >= int(settings["min_critical_authors"])
        and critical_ratio >= float(settings["critical_ratio_threshold"])
        and weighted_ratio >= float(settings["weighted_ratio_threshold"])
    )
    auxiliary_drop = (
        len(strong_critical_authors)
        >= int(settings["strong_critical_authors"])
        and weighted_ratio
        >= float(settings["strong_weighted_ratio_threshold"])
    )
    if primary_drop or auxiliary_drop:
        details["matched_rule"] = (
            "primary" if primary_drop else "strong_evidence"
        )
        return _stage_result("drop", "REPLIES_STRONG_CHALLENGE", details)
    return _stage_result("pass", "REPLIES_PASSED", details)


def apply_comment_filters(
    items: Iterable[Dict],
    provider: Optional[CommentProvider] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """批量执行可跳过的第三层筛选。"""
    candidates = list(items)
    if not candidates:
        return [], []

    enabled: List[Tuple[Dict, Dict[str, object]]] = []
    passed: List[Dict] = []
    for item in candidates:
        settings = _validated_settings(
            str(item.get("platform", "unknown") or "unknown")
        )
        if not settings.get("enabled"):
            append_filter_stage(
                item,
                _stage_result("skip", "COMMENTS_DISABLED"),
            )
            passed.append(item)
            continue
        enabled.append((item, settings))

    if not enabled:
        return passed, []

    if provider is None:
        fetched: Dict[str, CommentFetchResult] = {}
    else:
        try:
            fetched = provider.fetch_comments(
                [item for item, _settings in enabled],
                limit=max(
                    int(settings["max_comments"]) for _item, settings in enabled
                ),
                timeout_seconds=max(
                    float(settings["timeout_seconds"])
                    for _item, settings in enabled
                ),
            )
        except Exception:
            fetched = {}

    dropped: List[Dict] = []
    for item, settings in enabled:
        item_id = str(item.get("id", "") or "")
        fetch_result = fetched.get(
            item_id,
            CommentFetchResult(
                available=False,
                error="平台未返回该内容的评论结果",
            ),
        )
        result = evaluate_comments(item, fetch_result, settings)
        append_filter_stage(item, result)
        (dropped if result["decision"] == "drop" else passed).append(item)
    return passed, dropped
