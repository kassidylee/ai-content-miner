"""GitHub 三层筛选的批量编排。"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional

from analyzer.github_embedding import apply_github_embedding_filter
from analyzer.github_quality import apply_github_quality_filter
from analyzer.github_rules import apply_github_rules


def run_github_filters(
    items: Iterable[Dict],
    embedding_client: Optional[object] = None,
    now: Optional[datetime] = None,
) -> Dict[str, List[Dict]]:
    """依次执行仓库规则、关键词 Embedding 和质量评分。"""
    all_items = list(items)
    rule_passed, rule_dropped = apply_github_rules(all_items)
    embedding_passed, embedding_dropped = apply_github_embedding_filter(
        rule_passed,
        client=embedding_client,
    )
    quality_passed, quality_dropped = apply_github_quality_filter(
        embedding_passed,
        now=now,
    )
    for item in quality_passed:
        metadata = item["github_filter_metadata"]
        metadata["final_decision"] = "keep"
        metadata["final_reason_codes"] = ["GITHUB_FILTER_PIPELINE_PASSED"]
    return {
        "all_items": all_items,
        "passed": quality_passed,
        "dropped": rule_dropped + embedding_dropped + quality_dropped,
    }
