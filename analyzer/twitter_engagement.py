"""统一计算 Twitter 互动指标，供规则筛选和每日排序复用。"""

from __future__ import annotations

from typing import Dict

import config


def twitter_metric(item: Dict, name: str) -> int:
    """读取非负整数指标；缺失、布尔值和异常数据统一按零处理。"""
    metrics = item.get("metrics", {})
    if not isinstance(metrics, dict):
        return 0
    value = metrics.get(name, 0)
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def validate_twitter_engagement_config() -> None:
    """确保规则层和排序层读取到完整、可计算的互动权重。"""
    weights = getattr(config, "TWITTER_ENGAGEMENT_WEIGHTS", None)
    required = {
        "like_count",
        "reply_count",
        "share_count",
        "quote_count",
        "bookmark_count",
    }
    if not isinstance(weights, dict) or set(weights) != required:
        raise ValueError(
            "TWITTER_ENGAGEMENT_WEIGHTS 必须完整配置五类互动指标"
        )
    for name, value in weights.items():
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value < 0
        ):
            raise ValueError(
                f"TWITTER_ENGAGEMENT_WEIGHTS.{name} 必须是非负数"
            )


def weighted_twitter_engagement(item: Dict) -> float:
    """按传播和复用价值加权赞、评、转、引用与收藏。"""
    weights = config.TWITTER_ENGAGEMENT_WEIGHTS
    total = sum(
        twitter_metric(item, name) * float(weight)
        for name, weight in weights.items()
    )
    return round(total, 4)
