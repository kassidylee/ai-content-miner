"""Reddit 三层专用筛选、质量排序和末端限量的批量编排。"""

from __future__ import annotations

from datetime import datetime
from numbers import Integral
from typing import Dict, Iterable, List, Optional

import config
from analyzer.reddit_common import (
    append_reddit_filter_stage,
    reddit_filter_stage,
)
from analyzer.reddit_embedding import apply_reddit_embedding_filter
from analyzer.reddit_quality import apply_reddit_quality_filter
from analyzer.reddit_rules import apply_reddit_rules


def validate_reddit_pipeline_config() -> None:
    """校验只影响 Reddit 最终候选集的编排配置。"""
    limit = getattr(config, "REDDIT_FINAL_RESULT_LIMIT", None)
    if (
        not isinstance(limit, Integral)
        or isinstance(limit, bool)
        or int(limit) <= 0
    ):
        raise ValueError("REDDIT_FINAL_RESULT_LIMIT 必须是正整数")


def _quality_score(item: Dict) -> float:
    stage = reddit_filter_stage(item, "quality")
    try:
        return float(stage.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _rank_final_candidates(
    items: Iterable[Dict],
) -> tuple[List[Dict], List[Dict]]:
    """按质量分排序，只在全部筛选完成后限制最终候选数。"""
    validate_reddit_pipeline_config()
    ranked = sorted(items, key=_quality_score, reverse=True)
    limit = int(config.REDDIT_FINAL_RESULT_LIMIT)
    passed = ranked[:limit]
    overflow = ranked[limit:]

    for rank, item in enumerate(ranked, start=1):
        score = _quality_score(item)
        within_limit = rank <= limit
        append_reddit_filter_stage(
            item,
            {
                "stage": "ranking",
                "decision": "pass" if within_limit else "drop",
                "score": score,
                "reason_codes": [
                    (
                        "REDDIT_FINAL_RANKING_PASSED"
                        if within_limit
                        else "REDDIT_FINAL_RESULT_LIMIT_EXCEEDED"
                    )
                ],
                "details": {
                    "rank": rank,
                    "limit": limit,
                    "sorted_by": "quality_score_desc",
                },
            },
        )
        if within_limit:
            metadata = item["reddit_filter_metadata"]
            metadata["final_decision"] = "keep"
            metadata["final_reason_codes"] = [
                "REDDIT_FILTER_PIPELINE_PASSED"
            ]
    return passed, overflow


def run_reddit_filters(
    items: Iterable[Dict],
    embedding_client: Optional[object] = None,
    now: Optional[datetime] = None,
) -> Dict[str, List[Dict]]:
    """执行三层筛选，最后按质量分降序限制最终候选数量。"""
    validate_reddit_pipeline_config()
    all_items = list(items)
    rule_passed, rule_dropped = apply_reddit_rules(all_items)
    embedding_passed, embedding_dropped = apply_reddit_embedding_filter(
        rule_passed,
        client=embedding_client,
    )
    quality_passed, quality_dropped = apply_reddit_quality_filter(
        embedding_passed,
        now=now,
    )
    final_passed, ranking_dropped = _rank_final_candidates(quality_passed)
    return {
        "all_items": all_items,
        "passed": final_passed,
        "dropped": (
            rule_dropped
            + embedding_dropped
            + quality_dropped
            + ranking_dropped
        ),
    }
