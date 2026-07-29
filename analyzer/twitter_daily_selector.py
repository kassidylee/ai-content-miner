"""为每日 Twitter 简报聚类、排序并选择 8+4 条内容。"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import config
from analyzer.twitter_comments import apply_twitter_comment_filter
from analyzer.twitter_engagement import (
    twitter_metric,
    validate_twitter_engagement_config,
    weighted_twitter_engagement,
)


class TwitterDailySelectionConfigError(ValueError):
    """Twitter 每日选择配置无效。"""


_TOKEN_PATTERN = re.compile(
    r"[a-z0-9][a-z0-9._+-]*|[\u4e00-\u9fff]{2,20}",
    re.IGNORECASE,
)
_EVENT_STOPWORDS = {
    "ai",
    "agent",
    "agents",
    "agentic",
    "llm",
    "model",
    "models",
    "benchmark",
    "inference",
    "training",
    "quantization",
    "reinforcement",
    "learning",
    "multimodal",
    "vision",
    "video",
    "speech",
    "system",
    "technical",
    "release",
    "implementation",
    "details",
    "open",
    "source",
    "new",
    "anthropic",
    "claude",
    "developer",
    "every",
    "face",
    "google",
    "hugging",
    "meta",
    "microsoft",
    "openai",
    "repos",
    "repositories",
    "should",
    "a",
    "an",
    "and",
    "for",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "the",
    "this",
    "to",
    "with",
    "https",
    "t.co",
    "mcp",
    "rag",
    "github",
    "paper",
    "framework",
    "大模型",
    "模型",
    "智能体",
    "开源",
    "发布",
    "项目",
    "论文",
    "框架",
    "训练",
    "推理",
    "评测",
    "基准",
    "强化学习",
    "多模态",
    "视觉",
    "视频",
    "语音",
}
_NOVELTY_KEYWORDS = {
    "announce",
    "announced",
    "introducing",
    "launch",
    "launched",
    "release",
    "released",
    "open source",
    "technical report",
    "benchmark result",
    "new version",
    "update",
    "updated",
    "发布",
    "公布",
    "上线",
    "开源",
    "技术报告",
    "评测结果",
    "新版本",
    "更新",
}


def validate_twitter_daily_config() -> None:
    """校验每日配额和聚类配置。"""
    for name in (
        "TWITTER_DAILY_PRIMARY_LIMIT",
        "TWITTER_DAILY_MORE_LIMIT",
        "TWITTER_DAILY_AUTHOR_LIMIT",
        "TWITTER_DAILY_HISTORY_DAYS",
        "TWITTER_DAILY_STANDARD_MAX_AGE_HOURS",
        "TWITTER_DAILY_FALLBACK_MAX_AGE_HOURS",
    ):
        value = getattr(config, name, None)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise TwitterDailySelectionConfigError(f"{name} 必须是正整数")

    if (
        config.TWITTER_DAILY_STANDARD_MAX_AGE_HOURS
        >= config.TWITTER_DAILY_FALLBACK_MAX_AGE_HOURS
    ):
        raise TwitterDailySelectionConfigError(
            "Twitter 常规时间窗口必须小于高信号回退窗口"
        )
    topic_penalty = getattr(
        config,
        "TWITTER_DAILY_TOPIC_REPEAT_PENALTY",
        None,
    )
    if (
        not isinstance(topic_penalty, (int, float))
        or isinstance(topic_penalty, bool)
        or topic_penalty < 0
    ):
        raise TwitterDailySelectionConfigError(
            "TWITTER_DAILY_TOPIC_REPEAT_PENALTY 必须是非负数"
        )
    fallback_social = getattr(
        config,
        "TWITTER_DAILY_FALLBACK_MIN_SOCIAL_SCORE",
        None,
    )
    if (
        not isinstance(fallback_social, (int, float))
        or isinstance(fallback_social, bool)
        or not 0 <= float(fallback_social) <= 1
    ):
        raise TwitterDailySelectionConfigError(
            "TWITTER_DAILY_FALLBACK_MIN_SOCIAL_SCORE 必须在 0 到 1 之间"
        )
    minimum_engagement = getattr(
        config,
        "TWITTER_DAILY_MIN_WEIGHTED_ENGAGEMENT",
        None,
    )
    if (
        not isinstance(minimum_engagement, (int, float))
        or isinstance(minimum_engagement, bool)
        or minimum_engagement < 0
    ):
        raise TwitterDailySelectionConfigError(
            "TWITTER_DAILY_MIN_WEIGHTED_ENGAGEMENT 必须是非负数"
        )
    overlap = getattr(config, "TWITTER_DAILY_EVENT_TOKEN_OVERLAP", None)
    if (
        not isinstance(overlap, (int, float))
        or isinstance(overlap, bool)
        or not 0 < float(overlap) <= 1
    ):
        raise TwitterDailySelectionConfigError(
            "TWITTER_DAILY_EVENT_TOKEN_OVERLAP 必须在 0 到 1 之间"
        )
    try:
        ZoneInfo(str(config.TWITTER_DAILY_TIMEZONE))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TwitterDailySelectionConfigError(
            "TWITTER_DAILY_TIMEZONE 不是有效时区"
        ) from exc
    try:
        validate_twitter_engagement_config()
    except ValueError as exc:
        raise TwitterDailySelectionConfigError(str(exc)) from exc


def _text(item: Dict) -> str:
    return " ".join(
        str(item.get(name, "") or "")
        for name in ("title", "content", "quoted_content")
    ).casefold()


def _normalized_title(item: Dict) -> str:
    title = str(item.get("title", "") or "").casefold()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title)


def _event_tokens(item: Dict) -> set[str]:
    source = str(item.get("title", "") or "").casefold()
    return {
        token
        for token in _TOKEN_PATTERN.findall(source)
        if (
            token not in _EVENT_STOPWORDS
            and len(token) > 1
            and not token.replace(".", "").isdigit()
        )
    }


def _external_urls(item: Dict) -> set[str]:
    urls: set[str] = set()
    for entry in item.get("referenced_urls", []):
        if not isinstance(entry, dict):
            continue
        parsed = urlparse(str(entry.get("url", "") or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        domain = parsed.netloc.casefold().removeprefix("www.")
        path = parsed.path.rstrip("/")
        urls.add(f"{domain}{path}")
    return urls


def _same_event(left: Dict, right: Dict) -> bool:
    left_urls = _external_urls(left)
    right_urls = _external_urls(right)
    if left_urls and right_urls:
        shared_urls = left_urls.intersection(right_urls)
        if (
            shared_urls
            and max(len(left_urls), len(right_urls)) <= 3
            and len(shared_urls) / min(len(left_urls), len(right_urls))
            >= 0.5
        ):
            return True

    left_title = _normalized_title(left)
    right_title = _normalized_title(right)
    left_tokens = _event_tokens(left)
    right_tokens = _event_tokens(right)
    shared = left_tokens.intersection(right_tokens)
    title_ratio = 0.0
    if min(len(left_title), len(right_title)) >= 8:
        title_ratio = SequenceMatcher(
            None,
            left_title,
            right_title,
        ).ratio()
        if (
            shared
            and title_ratio >= 0.72
        ):
            return True

    smaller = min(len(left_tokens), len(right_tokens))
    if (
        len(shared) == 1
        and len(next(iter(shared))) >= 8
        and title_ratio >= 0.35
    ):
        return True
    if len(shared) < 2 or smaller == 0:
        return False
    return len(shared) / smaller >= float(
        config.TWITTER_DAILY_EVENT_TOKEN_OVERLAP
    )


def _stage_details(item: Dict, stage_name: str) -> Dict[str, object]:
    stages = item.get("filter_metadata", {}).get("stages", [])
    for stage in reversed(stages):
        if isinstance(stage, dict) and stage.get("stage") == stage_name:
            details = stage.get("details", {})
            return details if isinstance(details, dict) else {}
    return {}


def _embedding_stage(item: Dict) -> Dict[str, object]:
    stages = item.get("filter_metadata", {}).get("stages", [])
    for stage in reversed(stages):
        if isinstance(stage, dict) and stage.get("stage") == "embedding":
            return stage
    return {}


def _is_listicle(item: Dict) -> bool:
    title = str(item.get("title", "") or "").casefold()
    english = re.search(
        r"\b\d{1,2}\s+(?:open-source\s+)?(?:github\s+)?"
        r"(?:repos|repositories|projects|papers|tools)\b",
        title,
    )
    chinese = re.search(
        r"\d{1,2}\s*个.*(?:项目|仓库|论文|工具)|清单|合集",
        title,
    )
    return bool(english or chinese)


def _published_timestamp(item: Dict) -> float:
    value = item.get("published_at")
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(
                str(value or "").replace("Z", "+00:00")
            )
        except ValueError:
            return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _age_hours(item: Dict, now: datetime) -> float:
    """返回帖子年龄；缺少有效时间时使用无穷大，确保无法混入日刊。"""
    published = _published_timestamp(item)
    if published <= 0:
        return math.inf
    current = now
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (current.timestamp() - published) / 3600)


def _percentiles(
    items: Sequence[Dict],
    value_getter,
) -> Dict[str, float]:
    """计算并列值共享的分位排名，避免使用帖子 ID 人为打破平分。"""
    ordered = sorted(
        (
            (float(value_getter(item)), str(item.get("id", "") or ""))
            for item in items
        ),
        key=lambda entry: entry[0],
    )
    if len(ordered) <= 1:
        return {item_id: 1.0 for _value, item_id in ordered}

    percentiles: Dict[str, float] = {}
    start = 0
    while start < len(ordered):
        end = start
        while (
            end + 1 < len(ordered)
            # 两个百分点以内的微小差异通常来自发布时间取整或指标延迟，
            # 不足以证明真实质量差距，因此按并列处理，避免分位排名被放大。
            and math.isclose(
                ordered[end + 1][0],
                ordered[start][0],
                rel_tol=0.02,
                abs_tol=1e-9,
            )
        ):
            end += 1
        percentile = ((start + end) / 2) / (len(ordered) - 1)
        for index in range(start, end + 1):
            percentiles[ordered[index][1]] = percentile
        start = end + 1
    return percentiles


def _novelty(item: Dict) -> float:
    """用明确的发布和更新措辞衡量帖子是否包含新事件。"""
    searchable = _text(item)
    matches = sum(
        1 for keyword in _NOVELTY_KEYWORDS if keyword in searchable
    )
    return min(1.0, matches / 2)


def _score_items(
    items: Sequence[Dict],
    now: datetime,
) -> Dict[str, Dict[str, float]]:
    """生成以互动为主的可审计评分明细。"""
    item_ids = [str(item.get("id", "") or "") for item in items]
    ages = {
        item_id: _age_hours(item, now)
        for item_id, item in zip(item_ids, items)
    }
    weighted = {
        item_id: weighted_twitter_engagement(item)
        for item_id, item in zip(item_ids, items)
    }

    # 绝对互动体现社区总认可；速度避免新帖因累计时间短而吃亏；
    # 互动率衡量有限曝光是否转化成实际反馈。三者均使用本次候选分位数，
    # 以减小不同语言、账号规模和 X 指标量级变化带来的阈值漂移。
    velocities = {
        item_id: weighted[item_id] / math.pow(ages[item_id] + 2.0, 0.7)
        if math.isfinite(ages[item_id])
        else 0.0
        for item_id in item_ids
    }
    rates = {
        item_id: (
            weighted[item_id] / twitter_metric(item, "view_count")
            if twitter_metric(item, "view_count") > 0
            else 0.0
        )
        for item_id, item in zip(item_ids, items)
    }
    absolute_percentiles = _percentiles(
        items,
        lambda item: weighted[str(item.get("id", "") or "")],
    )
    velocity_percentiles = _percentiles(
        items,
        lambda item: velocities[str(item.get("id", "") or "")],
    )
    rate_percentiles = _percentiles(
        items,
        lambda item: rates[str(item.get("id", "") or "")],
    )

    scores: Dict[str, Dict[str, float]] = {}
    fallback_age = float(config.TWITTER_DAILY_FALLBACK_MAX_AGE_HOURS)
    for item in items:
        item_id = str(item.get("id", "") or "")
        rules = _stage_details(item, "rules")
        technical = max(
            0.0,
            min(1.0, float(rules.get("technical_score", 0) or 0) / 6),
        )
        evidence = 1.0 if rules.get("evidence_domains") else 0.0
        social_quality = (
            absolute_percentiles.get(item_id, 0.0) * 0.5
            + velocity_percentiles.get(item_id, 0.0) * 0.3
            + rate_percentiles.get(item_id, 0.0) * 0.2
        )
        novelty = _novelty(item)
        age = ages[item_id]
        freshness = (
            max(0.0, 1.0 - age / fallback_age)
            if math.isfinite(age)
            else 0.0
        )
        promotion_penalty = 10.0 if rules.get("promotion_penalties") else 0.0
        if _is_listicle(item):
            promotion_penalty += 15.0

        # 互动占六成，决定合格内容的主要顺序。其余维度只用于区分
        # 互动接近的帖子，不能让低互动内容依靠技术词或主题名额反超。
        score = (
            social_quality * 60
            + novelty * 15
            + evidence * 10
            + technical * 10
            + freshness * 5
            - promotion_penalty
        )
        scores[item_id] = {
            "score": round(score, 4),
            "social_quality": round(social_quality, 4),
            "weighted_engagement": round(weighted[item_id], 4),
            "engagement_velocity": round(velocities[item_id], 6),
            "engagement_rate": round(rates[item_id], 6),
            "novelty": round(novelty, 4),
            "evidence": round(evidence, 4),
            "technical": round(technical, 4),
            "freshness": round(freshness, 4),
            "promotion_penalty": round(promotion_penalty, 4),
            "age_hours": round(age, 4) if math.isfinite(age) else math.inf,
        }
    return scores


def _topic_bucket(item: Dict) -> str:
    embedding = _embedding_stage(item)
    best_topic = str(embedding.get("best_topic", "") or "").strip()
    if best_topic:
        return best_topic

    text = _text(item)
    if "reinforcement learning" in text or "强化学习" in text:
        return "reinforcement-learning"
    if any(
        keyword in text
        for keyword in (
            "multimodal",
            "vision",
            "video generation",
            "speech",
            "多模态",
            "视觉",
            "视频生成",
            "语音",
        )
    ):
        return "multimodal"
    if any(
        keyword in text
        for keyword in ("quantitative trading", "量化投资", "交易策略")
    ):
        return "quant-trading"
    if any(
        keyword in text
        for keyword in ("ai agent", "agentic", "智能体", "mcp", "rag")
    ):
        return "ai-agent"
    if any(
        keyword in text
        for keyword in (
            "inference",
            "training",
            "quantization",
            "推理",
            "训练",
            "量化",
        )
    ):
        return "llm-systems"
    return "ai-general"


def _author_key(item: Dict) -> str:
    author = str(
        item.get("username") or item.get("author") or item.get("id") or ""
    )
    return author.casefold().strip()


def _cluster_id(item: Dict) -> str:
    urls = sorted(_external_urls(item))
    tokens = sorted(_event_tokens(item))
    signature = urls[0] if urls else " ".join(tokens[:8])
    if not signature:
        signature = str(item.get("id", "") or "")
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]


def _set_publication(
    item: Dict,
    digest_date: str,
    decision: str,
    reason_code: str,
    **details: object,
) -> None:
    item["publication_metadata"] = {
        "digest_date": digest_date,
        "decision": decision,
        "reason_codes": [reason_code],
        **details,
    }


def _score_audit(details: Dict[str, float]) -> Dict[str, object]:
    """把总分和各分项写入结果，便于解释每条内容的入选原因。"""
    return {
        "score": details["score"],
        "score_breakdown": {
            "social_quality": details["social_quality"],
            "novelty": details["novelty"],
            "evidence": details["evidence"],
            "technical": details["technical"],
            "freshness": details["freshness"],
            "promotion_penalty": details["promotion_penalty"],
        },
        "engagement_metrics": {
            "weighted_engagement": details["weighted_engagement"],
            "velocity": details["engagement_velocity"],
            "rate": details["engagement_rate"],
        },
        "age_hours": details["age_hours"],
    }


def _cluster_candidates(
    candidates: Sequence[Dict],
) -> List[List[Dict]]:
    clusters: List[List[Dict]] = []
    for item in candidates:
        for cluster in clusters:
            if _same_event(item, cluster[0]):
                cluster.append(item)
                break
        else:
            clusters.append([item])
    return clusters


def _digest_date(now: Optional[datetime]) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(ZoneInfo(config.TWITTER_DAILY_TIMEZONE))
    return local.date().isoformat()


def select_twitter_daily_items(
    items: Iterable[Dict],
    reply_provider: Optional[object] = None,
    recent_history: Iterable[Dict] = (),
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    """从全部合格候选中惰性检查回复并选择每日内容。"""
    validate_twitter_daily_config()
    candidates = list(items)
    history = list(recent_history)
    digest_date = _digest_date(now)
    if not candidates:
        return {
            "digest_date": digest_date,
            "primary": [],
            "more": [],
            "selected": [],
            "archived": [],
            "comment_dropped": [],
        }

    score_now = now or datetime.now(timezone.utc)
    if score_now.tzinfo is None:
        score_now = score_now.replace(tzinfo=timezone.utc)
    scores = _score_items(candidates, score_now)
    eligible: List[Dict] = []
    standard_age = float(config.TWITTER_DAILY_STANDARD_MAX_AGE_HOURS)
    fallback_age = float(config.TWITTER_DAILY_FALLBACK_MAX_AGE_HOURS)
    fallback_social = float(
        config.TWITTER_DAILY_FALLBACK_MIN_SOCIAL_SCORE
    )
    minimum_engagement = float(
        config.TWITTER_DAILY_MIN_WEIGHTED_ENGAGEMENT
    )
    for item in candidates:
        item_id = str(item.get("id", "") or "")
        score_details = scores[item_id]
        if any(_same_event(item, previous) for previous in history):
            _set_publication(
                item,
                digest_date,
                "archive",
                "TWITTER_DAILY_RECENT_EVENT",
                **_score_audit(score_details),
            )
        elif score_details["age_hours"] > fallback_age:
            _set_publication(
                item,
                digest_date,
                "archive",
                "TWITTER_DAILY_TOO_OLD",
                **_score_audit(score_details),
            )
        elif score_details["weighted_engagement"] < minimum_engagement:
            # 相对分位数在候选很少时可能夸大弱互动，因此最终发布还需要
            # 一个绝对底线。未达标内容保留审计记录，但不会用于填充名额。
            _set_publication(
                item,
                digest_date,
                "archive",
                "TWITTER_DAILY_LOW_SOCIAL_SIGNAL",
                **_score_audit(score_details),
            )
        elif (
            score_details["age_hours"] > standard_age
            and (
                score_details["social_quality"] < fallback_social
                or not _stage_details(item, "rules").get(
                    "evidence_domains"
                )
            )
        ):
            # 较旧内容只有同时具备高互动和一手证据才有资格进入日刊。
            # 这条窄例外允许高价值项目或论文继续竞争，但不会把普通旧帖带回来。
            _set_publication(
                item,
                digest_date,
                "archive",
                "TWITTER_DAILY_STALE_LOW_SIGNAL",
                **_score_audit(score_details),
            )
        else:
            eligible.append(item)

    representatives: List[Tuple[float, Dict]] = []
    for cluster in _cluster_candidates(eligible):
        ordered = sorted(
            cluster,
            key=lambda item: (
                scores[str(item.get("id", "") or "")]["score"],
                _published_timestamp(item),
                str(item.get("id", "") or ""),
            ),
            reverse=True,
        )
        representative = ordered[0]
        cluster_key = _cluster_id(representative)
        related_ids = [
            str(item.get("id", "") or "")
            for item in ordered[1:]
        ]
        _set_publication(
            representative,
            digest_date,
            "archive",
            "TWITTER_DAILY_NOT_SELECTED",
            **_score_audit(
                scores[str(representative.get("id", "") or "")]
            ),
            cluster_id=cluster_key,
            related_source_ids=related_ids,
        )
        for duplicate in ordered[1:]:
            _set_publication(
                duplicate,
                digest_date,
                "cluster_duplicate",
                "TWITTER_DAILY_CLUSTER_DUPLICATE",
                **_score_audit(
                    scores[str(duplicate.get("id", "") or "")]
                ),
                cluster_id=cluster_key,
                representative_id=str(
                    representative.get("id", "") or ""
                ),
            )
        representatives.append(
            (
                scores[str(representative.get("id", "") or "")]["score"],
                representative,
            )
        )

    representatives.sort(
        key=lambda entry: (
            entry[0],
            _published_timestamp(entry[1]),
            str(entry[1].get("id", "") or ""),
        ),
        reverse=True,
    )
    base_ranks = {
        id(item): rank
        for rank, (_score, item) in enumerate(
            representatives,
            start=1,
        )
    }
    for _score, item in representatives:
        item["publication_metadata"]["base_rank"] = base_ranks[id(item)]

    primary_limit = int(config.TWITTER_DAILY_PRIMARY_LIMIT)
    more_limit = int(config.TWITTER_DAILY_MORE_LIMIT)
    total_limit = primary_limit + more_limit
    author_limit = int(config.TWITTER_DAILY_AUTHOR_LIMIT)
    topic_penalty = float(config.TWITTER_DAILY_TOPIC_REPEAT_PENALTY)
    author_counts: Dict[str, int] = {}
    topic_counts: Dict[str, int] = {}
    selected: List[Dict] = []
    comment_dropped: List[Dict] = []
    remaining = list(representatives)

    # 每轮都根据已经选择的主题重新计算排序分。重复主题只扣分，
    # 不会像旧逻辑那样在每类两条后停止，因此主题结构不会限制 8+4 容量。
    while remaining and len(selected) < total_limit:
        options: List[Tuple[float, float, Dict, str, str]] = []
        still_eligible: List[Tuple[float, Dict]] = []
        for base_score, item in remaining:
            author = _author_key(item)
            topic = _topic_bucket(item)
            metadata = item["publication_metadata"]
            metadata["topic"] = topic
            if author_counts.get(author, 0) >= author_limit:
                metadata["reason_codes"] = [
                    "TWITTER_DAILY_AUTHOR_LIMIT"
                ]
                continue
            selection_score = (
                base_score
                - topic_penalty * topic_counts.get(topic, 0)
            )
            options.append(
                (
                    selection_score,
                    base_score,
                    item,
                    author,
                    topic,
                )
            )
            still_eligible.append((base_score, item))

        remaining = still_eligible
        if not options:
            break
        selection_score, base_score, item, author, topic = max(
            options,
            key=lambda option: (
                option[0],
                option[1],
                _published_timestamp(option[2]),
                str(option[2].get("id", "") or ""),
            ),
        )
        remaining = [
            entry for entry in remaining if entry[1] is not item
        ]

        # 回复检查只对下一条最可能入选的内容执行。若评论区出现可靠质疑，
        # 该条立即淘汰并继续选择下一名，直到填满容量或候选耗尽。
        passed, dropped = apply_twitter_comment_filter(
            [item],
            reply_provider=reply_provider,
        )
        if dropped:
            item_id = str(item.get("id", "") or "")
            _set_publication(
                item,
                digest_date,
                "drop",
                "TWITTER_DAILY_REPLY_REJECTED",
                **_score_audit(scores[item_id]),
                base_rank=base_ranks[id(item)],
                selection_score=round(selection_score, 4),
                topic=topic,
            )
            comment_dropped.extend(dropped)
            continue
        if not passed:
            continue

        previous = item["publication_metadata"]
        decision = "primary" if len(selected) < primary_limit else "more"
        item_id = str(item.get("id", "") or "")
        _set_publication(
            item,
            digest_date,
            decision,
            "TWITTER_DAILY_SELECTED",
            **_score_audit(scores[item_id]),
            rank=len(selected) + 1,
            base_rank=base_ranks[id(item)],
            selection_score=round(selection_score, 4),
            topic=topic,
            cluster_id=previous.get("cluster_id", ""),
            related_source_ids=previous.get("related_source_ids", []),
        )
        selected.append(item)
        author_counts[author] = author_counts.get(author, 0) + 1
        topic_counts[topic] = topic_counts.get(topic, 0) + 1

    primary = selected[:primary_limit]
    more = selected[primary_limit:total_limit]
    selected_ids = {id(item) for item in selected}
    dropped_ids = {id(item) for item in comment_dropped}
    archived = [
        item
        for item in candidates
        if id(item) not in selected_ids and id(item) not in dropped_ids
    ]
    return {
        "digest_date": digest_date,
        "primary": primary,
        "more": more,
        "selected": selected,
        "archived": archived,
        "comment_dropped": comment_dropped,
    }
