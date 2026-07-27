"""Reddit 专用筛选的第三层内容质量评分。"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from numbers import Real
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import config
from analyzer.reddit_common import (
    append_reddit_filter_stage,
    raw_reddit_record,
    reddit_filter_stage,
)


COMPONENT_NAMES = (
    "relevance",
    "depth",
    "evidence",
    "freshness",
    "source_quality",
)


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _published_at(item: Dict) -> Optional[datetime]:
    value = item.get("publish_time")
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _valid_http_url(value: object) -> bool:
    parsed = urlparse(_clean(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_reddit_quality_config() -> None:
    threshold = getattr(config, "REDDIT_QUALITY_MIN_SCORE", None)
    if (
        not isinstance(threshold, Real)
        or isinstance(threshold, bool)
        or not 0 <= float(threshold) <= 10
    ):
        raise ValueError("REDDIT_QUALITY_MIN_SCORE 必须在 0 到 10 之间")

    weights = getattr(config, "REDDIT_QUALITY_WEIGHTS", None)
    if not isinstance(weights, dict):
        raise ValueError("REDDIT_QUALITY_WEIGHTS 必须是字典")
    if set(weights) != set(COMPONENT_NAMES):
        raise ValueError(
            "REDDIT_QUALITY_WEIGHTS 必须只包含 "
            + "、".join(COMPONENT_NAMES)
        )
    if any(
        not isinstance(value, Real)
        or isinstance(value, bool)
        or float(value) < 0
        for value in weights.values()
    ):
        raise ValueError("REDDIT_QUALITY_WEIGHTS 权重必须是非负数字")
    if not math.isclose(
        sum(float(value) for value in weights.values()),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise ValueError("REDDIT_QUALITY_WEIGHTS 权重之和必须为 1")


def _depth_score(item: Dict) -> Tuple[float, Dict[str, object]]:
    title = _clean(item.get("title"))
    content = str(item.get("content", "") or "")
    meaningful_chars = len("".join(content.split()))
    if meaningful_chars < 80:
        score = 0.3
    elif meaningful_chars < 200:
        score = 0.7
    elif meaningful_chars < 500:
        score = 1.1
    elif meaningful_chars < 1000:
        score = 1.5
    else:
        score = 1.7

    has_code = "```" in content or bool(
        re.search(r"\b(def|class|import|from|npm|pip|docker)\b", content)
    )
    has_structure = bool(
        re.search(r"(?m)^\s*(?:[-*]|\d+\.)\s+", content)
    )
    deep_terms = (
        "architecture",
        "benchmark",
        "evaluation",
        "implementation",
        "inference",
        "quantization",
        "training",
        "methodology",
        "架构",
        "评测",
        "实现",
        "推理",
        "量化",
        "训练",
        "方法",
    )
    searchable = f"{title}\n{content}".casefold()
    has_technical_detail = any(term in searchable for term in deep_terms)
    score += 0.1 if has_code else 0.0
    score += 0.1 if has_structure else 0.0
    score += 0.1 if has_technical_detail else 0.0
    return min(2.0, score), {
        "meaningful_chars": meaningful_chars,
        "has_code": has_code,
        "has_structure": has_structure,
        "has_technical_detail": has_technical_detail,
    }


def _evidence_score(item: Dict) -> Tuple[float, Dict[str, object]]:
    raw = raw_reddit_record(item)
    content = str(item.get("content", "") or "")
    external_url = _clean(raw.get("external_url"))
    has_external_url = _valid_http_url(external_url)
    has_inline_url = bool(re.search(r"https?://\S+", content))
    evidence_terms = (
        "arxiv",
        "doi.org",
        "github.com",
        "huggingface.co",
        "paper",
        "repository",
        "benchmark",
        "论文",
        "代码",
        "仓库",
        "基准",
    )
    searchable = f"{external_url}\n{content}".casefold()
    has_traceable_reference = any(
        term in searchable for term in evidence_terms
    )
    has_code = "```" in content
    has_structure = bool(
        re.search(r"(?m)^\s*(?:[-*]|\d+\.)\s+", content)
    )

    score = 0.2
    score += 0.8 if has_external_url else 0.0
    score += 0.35 if has_inline_url else 0.0
    score += 0.4 if has_traceable_reference else 0.0
    score += 0.15 if has_code else 0.0
    score += 0.1 if has_structure else 0.0
    return min(2.0, score), {
        "external_url": external_url,
        "has_external_url": has_external_url,
        "has_inline_url": has_inline_url,
        "has_traceable_reference": has_traceable_reference,
    }


def _freshness_score(
    item: Dict,
    now: datetime,
) -> Tuple[float, Optional[float]]:
    published_at = _published_at(item)
    if published_at is None:
        return 0.5, None
    age_days = max(
        0.0,
        (now - published_at.astimezone(timezone.utc)).total_seconds() / 86400,
    )
    if age_days <= 1:
        return 2.0, age_days
    if age_days <= 3:
        return 1.7, age_days
    if age_days <= 7:
        return 1.3, age_days
    if age_days <= 14:
        return 0.8, age_days
    return 0.4, age_days


def _source_quality_score(item: Dict) -> Tuple[float, Dict[str, object]]:
    raw = raw_reddit_record(item)
    post_url = _clean(item.get("url"))
    parsed_url = urlparse(post_url)
    valid_reddit_url = (
        parsed_url.scheme == "https"
        and parsed_url.netloc.casefold()
        in {"reddit.com", "www.reddit.com", "old.reddit.com"}
    )
    subreddit = _clean(
        raw.get("subreddit") or raw.get("search_subreddit")
    )
    author = _clean(item.get("author"))
    has_author = bool(author) and author.casefold() not in {
        "[deleted]",
        "deleted",
    }
    matched_keywords = raw.get("matched_keywords", [])
    has_collection_match = (
        isinstance(matched_keywords, list) and bool(matched_keywords)
    )

    score = 0.2
    score += 0.6 if valid_reddit_url else 0.0
    score += 0.5 if subreddit else 0.0
    score += 0.4 if has_author else 0.0
    score += 0.3 if has_collection_match else 0.0
    return min(2.0, score), {
        "subreddit": subreddit,
        "has_author": has_author,
        "has_collection_match": has_collection_match,
        "valid_reddit_url": valid_reddit_url,
    }


def evaluate_reddit_quality(
    item: Dict,
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    """按 Reddit 可用字段计算 0–10 分，完全忽略缺失互动指标。"""
    validate_reddit_quality_config()
    active_now = now or datetime.now(timezone.utc)
    if active_now.tzinfo is None:
        active_now = active_now.replace(tzinfo=timezone.utc)
    else:
        active_now = active_now.astimezone(timezone.utc)

    embedding = reddit_filter_stage(item, "embedding")
    best_score = float(embedding.get("best_score", 0.0) or 0.0)
    relevance = max(0.0, min(2.0, best_score * 2.0))
    depth, depth_details = _depth_score(item)
    evidence, evidence_details = _evidence_score(item)
    freshness, age_days = _freshness_score(item, active_now)
    source_quality, source_details = _source_quality_score(item)

    components = {
        "relevance": relevance,
        "depth": depth,
        "evidence": evidence,
        "freshness": freshness,
        "source_quality": source_quality,
    }
    weights = {
        name: float(config.REDDIT_QUALITY_WEIGHTS[name])
        for name in COMPONENT_NAMES
    }
    total_score = round(
        sum(
            components[name] * weights[name] * 5.0
            for name in COMPONENT_NAMES
        ),
        2,
    )
    threshold = float(config.REDDIT_QUALITY_MIN_SCORE)
    decision = "pass" if total_score >= threshold else "drop"
    raw = raw_reddit_record(item)
    return {
        "stage": "quality",
        "decision": decision,
        "score": total_score,
        "threshold": threshold,
        "components": {
            name: round(value, 2)
            for name, value in components.items()
        },
        "weights": weights,
        "details": {
            "best_topic": embedding.get("best_topic", ""),
            "best_topic_label": embedding.get("best_topic_label", ""),
            "published_age_days": (
                round(age_days, 2) if age_days is not None else None
            ),
            "metrics_available": raw.get("metrics_available") is True,
            "interaction_metrics_used": False,
            "depth": depth_details,
            "evidence": evidence_details,
            "source": source_details,
        },
        "reason_codes": [
            "REDDIT_QUALITY_SCORE_PASSED"
            if decision == "pass"
            else "REDDIT_QUALITY_SCORE_TOO_LOW"
        ],
    }


def apply_reddit_quality_filter(
    items: Iterable[Dict],
    now: Optional[datetime] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """批量执行 Reddit 内容质量评分。"""
    passed: List[Dict] = []
    dropped: List[Dict] = []
    for item in items:
        result = evaluate_reddit_quality(item, now=now)
        append_reddit_filter_stage(item, result)
        (passed if result["decision"] == "pass" else dropped).append(item)
    return passed, dropped
