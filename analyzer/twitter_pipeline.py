"""Twitter 三层筛选的批量编排。"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from analyzer.twitter_comments import apply_twitter_comment_filter
from analyzer.twitter_embedding import apply_twitter_embedding_filter
from analyzer.twitter_rules import apply_twitter_rules


def run_twitter_filters(
    items: Iterable[Dict],
    embedding_client: Optional[object] = None,
    reply_provider: Optional[object] = None,
) -> Dict[str, List[Dict]]:
    """依次执行规则、Embedding 和回复筛选。"""
    all_items = list(items)
    rule_passed, rule_dropped = apply_twitter_rules(all_items)
    embedding_passed, embedding_dropped = apply_twitter_embedding_filter(
        rule_passed,
        client=embedding_client,
    )
    comment_passed, comment_dropped = apply_twitter_comment_filter(
        embedding_passed,
        reply_provider=reply_provider,
    )
    return {
        "all_items": all_items,
        "passed": comment_passed,
        "dropped": (
            rule_dropped + embedding_dropped + comment_dropped
        ),
    }
