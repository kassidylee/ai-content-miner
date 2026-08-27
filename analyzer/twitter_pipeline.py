"""Twitter 三层筛选的批量编排。"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import config
from analyzer.twitter_comments import apply_twitter_comment_filter
from analyzer.twitter_common import append_twitter_filter_stage
from analyzer.twitter_embedding import apply_twitter_embedding_filter
from analyzer.twitter_rules import apply_twitter_rules


def run_twitter_filters(
    items: Iterable[Dict],
    embedding_client: Optional[object] = None,
    reply_provider: Optional[object] = None,
) -> Dict[str, List[Dict]]:
    """依次执行规则、Embedding 和回复筛选。"""
    preselected = run_twitter_preselection_filters(
        items,
        embedding_client=embedding_client,
    )
    comment_passed, comment_dropped = apply_twitter_comment_filter(
        preselected["passed"],
        reply_provider=reply_provider,
    )
    return {
        "all_items": preselected["all_items"],
        "passed": comment_passed,
        "dropped": preselected["dropped"] + comment_dropped,
    }


def run_twitter_preselection_filters(
    items: Iterable[Dict],
    embedding_client: Optional[object] = None,
) -> Dict[str, List[Dict]]:
    """执行适合全量候选的规则和 Embedding 筛选。"""
    all_items = list(items)

    # 本地规则先删除无关内容，避免浪费外部接口配额。
    rule_passed, rule_dropped = apply_twitter_rules(all_items)
    if getattr(config, "TWITTER_EMBEDDING_ENABLED", True):
        embedding_passed, embedding_dropped = apply_twitter_embedding_filter(
            rule_passed,
            client=embedding_client,
        )
    else:
        # 显式记录禁用状态，便于审计筛选过程。
        embedding_passed = list(rule_passed)
        embedding_dropped = []
        for item in embedding_passed:
            append_twitter_filter_stage(
                item,
                {
                    "stage": "embedding",
                    "decision": "pass",
                    "mode": "disabled",
                    "topic_scores": {},
                    "matched_topics": [],
                    "best_topic": "",
                    "best_score": 0.0,
                    "reason_codes": ["TWITTER_EMBEDDING_DISABLED"],
                },
            )
    return {
        "all_items": all_items,
        "passed": embedding_passed,
        "dropped": rule_dropped + embedding_dropped,
    }
