"""跨平台内容筛选编排。"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from analyzer.comment_filter import apply_comment_filters
from analyzer.embedding_filter import apply_embedding_filters
from analyzer.filter import apply_rule_filters
from crawler.base import CommentProvider


def run_initial_filters(
    items: Iterable[Dict],
    embedding_client: Optional[object] = None,
) -> Dict[str, List[Dict]]:
    """依次执行规则和 Embedding，保留全部审计记录。"""
    all_items = list(items)
    rule_passed, rule_dropped = apply_rule_filters(all_items)
    embedding_passed, embedding_dropped = apply_embedding_filters(
        rule_passed, client=embedding_client
    )
    return {
        "all_items": all_items,
        "passed": embedding_passed,
        "dropped": rule_dropped + embedding_dropped,
    }


def run_filter_pipeline(
    items: Iterable[Dict],
    embedding_client: Optional[object] = None,
    comment_provider: Optional[CommentProvider] = None,
) -> Dict[str, List[Dict]]:
    """依次执行三层筛选，平台评论能力可以缺省。"""
    initial = run_initial_filters(items, embedding_client=embedding_client)
    comment_passed, comment_dropped = apply_comment_filters(
        initial["passed"],
        provider=comment_provider,
    )
    return {
        "all_items": initial["all_items"],
        "passed": comment_passed,
        "dropped": initial["dropped"] + comment_dropped,
    }
