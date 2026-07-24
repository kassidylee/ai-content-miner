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
    all_items = list(items)

    # 第一层完全在本地执行，先删除无关内容，避免浪费外部接口配额。
    rule_passed, rule_dropped = apply_twitter_rules(all_items)
    if getattr(config, "TWITTER_EMBEDDING_ENABLED", True):
        embedding_passed, embedding_dropped = apply_twitter_embedding_filter(
            rule_passed,
            client=embedding_client,
        )
    else:
        # 禁用时仍写入一个显式阶段，保证 JSONL 能区分“跳过”和“已执行通过”。
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
    # 回复区只检查多来源的强质疑，不负责判断 AI 主题或技术深度。
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
