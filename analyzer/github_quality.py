"""GitHub 仓库筛选的第三层质量评分。"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import config
from analyzer.github_common import append_github_filter_stage


def _raw(item: Dict) -> Dict:
    value = item.get("raw", {})
    return value if isinstance(value, dict) else {}


def _count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _stage(item: Dict, name: str) -> Dict:
    metadata = item.get("github_filter_metadata", {})
    stages = metadata.get("stages", []) if isinstance(metadata, dict) else []
    for stage in reversed(stages):
        if isinstance(stage, dict) and stage.get("stage") == name:
            return stage
    return {}


def _published_at(item: Dict) -> Optional[datetime]:
    value = item.get("publish_time")
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def validate_github_quality_config() -> None:
    threshold = getattr(config, "GITHUB_QUALITY_MIN_SCORE", None)
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 10:
        raise ValueError("GITHUB_QUALITY_MIN_SCORE 必须在 0 到 10 之间")


def evaluate_github_quality(
    item: Dict,
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    """以相关度、文档、社区、活跃度和元数据计算 0-10 分。"""
    validate_github_quality_config()
    raw = _raw(item)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    embedding = _stage(item, "embedding")
    best_score = float(embedding.get("best_score", 0.0) or 0.0)
    relevance = max(0.0, min(2.0, best_score * 2.0))

    description = str(raw.get("description", "") or "").strip()
    readme = str(raw.get("readme", "") or "").strip()
    docs = 0.0
    if description:
        docs += 0.6
    if len(readme) >= 500:
        docs += 1.4
    elif readme:
        docs += 0.8

    stars = _count(raw.get("stars") or raw.get("stargazers_count"))
    forks = _count(raw.get("forks") or raw.get("forks_count"))
    community = min(1.6, math.log10(stars + 1) / 3 * 1.6)
    community += min(0.4, math.log10(forks + 1) / 3 * 0.4)

    published_at = _published_at(item)
    active = 0.0
    age_days = None
    if published_at is not None:
        age_days = max(0.0, (now - published_at).total_seconds() / 86400)
        if age_days <= 7:
            active = 2.0
        elif age_days <= 30:
            active = 1.5
        elif age_days <= 90:
            active = 1.0
        else:
            active = 0.5

    topics = raw.get("topics", [])
    metadata = 0.0
    if isinstance(topics, list) and topics:
        metadata += 0.5
    if str(raw.get("language", "") or "").strip():
        metadata += 0.2
    if str(raw.get("license", "") or "").strip() not in {"", "NOASSERTION"}:
        metadata += 0.3

    total_score = round(relevance + docs + community + active + metadata, 2)
    threshold = float(config.GITHUB_QUALITY_MIN_SCORE)
    decision = "pass" if total_score >= threshold else "drop"
    return {
        "stage": "quality",
        "decision": decision,
        "score": total_score,
        "threshold": threshold,
        "components": {
            "relevance": round(relevance, 2),
            "documentation": round(docs, 2),
            "community": round(community, 2),
            "activity": round(active, 2),
            "metadata": round(metadata, 2),
        },
        "details": {
            "stars": stars,
            "forks": forks,
            "pushed_age_days": round(age_days, 2) if age_days is not None else None,
        },
        "reason_codes": [
            "GITHUB_QUALITY_SCORE_PASSED"
            if decision == "pass"
            else "GITHUB_QUALITY_SCORE_TOO_LOW"
        ],
    }


def apply_github_quality_filter(
    items: Iterable[Dict],
    now: Optional[datetime] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """批量执行 GitHub 仓库质量评分。"""
    passed: List[Dict] = []
    dropped: List[Dict] = []
    for item in items:
        result = evaluate_github_quality(item, now=now)
        append_github_filter_stage(item, result)
        (passed if result["decision"] == "pass" else dropped).append(item)
    return passed, dropped
