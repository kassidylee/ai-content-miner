"""Reddit 专用筛选的第二层主题 Embedding 相关度。"""

from __future__ import annotations

import re
from numbers import Real
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import config
from analyzer.reddit_common import (
    append_reddit_filter_stage,
    raw_reddit_record,
)
from utils.embedding import (
    EmbeddingError,
    cosine_similarity,
    create_client,
    encode,
)


class RedditEmbeddingError(RuntimeError):
    """Reddit Embedding 配置、请求或向量格式错误。"""


def _clean(value: object) -> str:
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _configured_topics() -> List[Dict[str, object]]:
    configured = getattr(config, "REDDIT_INTEREST_TOPICS", None)
    if not isinstance(configured, list) or not configured:
        raise RedditEmbeddingError(
            "REDDIT_INTEREST_TOPICS 必须是非空主题列表"
        )

    topics: List[Dict[str, object]] = []
    seen_ids = set()
    for index, value in enumerate(configured):
        if not isinstance(value, dict):
            raise RedditEmbeddingError(
                f"REDDIT_INTEREST_TOPICS[{index}] 必须是字典"
            )
        topic_id = _clean(value.get("id"))
        label = _clean(value.get("label"))
        description = _clean(value.get("description"))
        threshold = value.get("threshold")
        if not topic_id or not label or not description:
            raise RedditEmbeddingError(
                f"REDDIT_INTEREST_TOPICS[{index}] 缺少 id、label 或 description"
            )
        if topic_id.casefold() in seen_ids:
            raise RedditEmbeddingError(
                f"REDDIT_INTEREST_TOPICS 包含重复 id：{topic_id}"
            )
        if (
            not isinstance(threshold, Real)
            or isinstance(threshold, bool)
            or not 0 <= float(threshold) <= 1
        ):
            raise RedditEmbeddingError(
                f"REDDIT_INTEREST_TOPICS[{index}].threshold 必须在 0 到 1 之间"
            )
        seen_ids.add(topic_id.casefold())
        topics.append(
            {
                "id": topic_id,
                "label": label,
                "description": description,
                "threshold": float(threshold),
            }
        )
    return topics


def validate_reddit_embedding_config(
    require_credentials: bool = True,
) -> None:
    mode = str(config.REDDIT_EMBEDDING_FILTER_MODE).strip().casefold()
    if mode not in {"shadow", "enforce"}:
        raise RedditEmbeddingError(
            "REDDIT_EMBEDDING_FILTER_MODE 只能是 shadow 或 enforce"
        )
    if not str(config.REDDIT_EMBEDDING_MODEL).strip():
        raise RedditEmbeddingError("REDDIT_EMBEDDING_MODEL 不能为空")
    if require_credentials:
        if not str(config.REDDIT_EMBEDDING_API_KEY or "").strip():
            raise RedditEmbeddingError("REDDIT_EMBEDDING_API_KEY 未配置")
        base_url = str(config.REDDIT_EMBEDDING_BASE_URL or "").strip()
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RedditEmbeddingError(
                "REDDIT_EMBEDDING_BASE_URL 必须是有效的 http/https URL"
            )
    if (
        not isinstance(config.REDDIT_EMBEDDING_BATCH_SIZE, int)
        or isinstance(config.REDDIT_EMBEDDING_BATCH_SIZE, bool)
        or config.REDDIT_EMBEDDING_BATCH_SIZE <= 0
    ):
        raise RedditEmbeddingError(
            "REDDIT_EMBEDDING_BATCH_SIZE 必须是正整数"
        )
    if (
        not isinstance(config.REDDIT_EMBEDDING_MAX_CHARS, int)
        or isinstance(config.REDDIT_EMBEDDING_MAX_CHARS, bool)
        or config.REDDIT_EMBEDDING_MAX_CHARS <= 0
    ):
        raise RedditEmbeddingError(
            "REDDIT_EMBEDDING_MAX_CHARS 必须是正整数"
        )
    _configured_topics()


def build_reddit_embedding_text(item: Dict) -> str:
    """组合正文语义与来源上下文，明确排除互动数和作者画像。"""
    raw = raw_reddit_record(item)
    sections: List[str] = []
    title = _clean(item.get("title"))
    if title:
        sections.append(f"标题：{title}")
    content = _clean(item.get("content"))
    if content and content != title:
        sections.append(f"正文：{content}")
    subreddit = _clean(
        raw.get("subreddit") or raw.get("search_subreddit")
    )
    if subreddit:
        sections.append(f"社区：r/{subreddit}")
    external_url = _clean(raw.get("external_url"))
    external_host = urlparse(external_url).netloc
    if external_host:
        sections.append(f"外部来源：{external_host.casefold()}")
    limit = int(config.REDDIT_EMBEDDING_MAX_CHARS)
    return "\n\n".join(sections)[:limit].strip()


def _embed_texts(
    client: object,
    texts: Sequence[str],
) -> List[List[float]]:
    try:
        return encode(
            texts,
            client=client,
            model=config.REDDIT_EMBEDDING_MODEL,
            batch_size=config.REDDIT_EMBEDDING_BATCH_SIZE,
        )
    except (EmbeddingError, ValueError) as exc:
        raise RedditEmbeddingError(str(exc)) from exc


def probe_reddit_embedding_service(
    client: Optional[object] = None,
) -> int:
    """请求一个主题向量，返回维度，用于启动前连通性检查。"""
    validate_reddit_embedding_config(require_credentials=client is None)
    active_client = client or create_client(
        api_key=config.REDDIT_EMBEDDING_API_KEY,
        base_url=config.REDDIT_EMBEDDING_BASE_URL,
    )
    vectors = _embed_texts(
        active_client,
        [str(_configured_topics()[0]["description"])],
    )
    if not vectors or not vectors[0]:
        raise RedditEmbeddingError("Reddit Embedding 探测返回了空向量")
    return len(vectors[0])


def _similarity(
    item_vector: Sequence[Real],
    topic_vector: Sequence[Real],
) -> float:
    try:
        return cosine_similarity(item_vector, topic_vector)
    except ValueError as exc:
        raise RedditEmbeddingError(
            f"Reddit Embedding 向量无法比较：{exc}"
        ) from exc


def apply_reddit_embedding_filter(
    items: Iterable[Dict],
    client: Optional[object] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """比较每篇 Reddit 内容与平台兴趣主题。"""
    candidates = list(items)
    if not candidates:
        return [], []
    validate_reddit_embedding_config(require_credentials=client is None)
    topics = _configured_topics()
    mode = str(config.REDDIT_EMBEDDING_FILTER_MODE).strip().casefold()
    active_client = client or create_client(
        api_key=config.REDDIT_EMBEDDING_API_KEY,
        base_url=config.REDDIT_EMBEDDING_BASE_URL,
    )

    passed: List[Dict] = []
    dropped: List[Dict] = []
    nonempty_items: List[Dict] = []
    item_texts: List[str] = []
    for item in candidates:
        text = build_reddit_embedding_text(item)
        if text:
            nonempty_items.append(item)
            item_texts.append(text)
            continue
        decision = "shadow_drop" if mode == "shadow" else "drop"
        append_reddit_filter_stage(
            item,
            {
                "stage": "embedding",
                "decision": decision,
                "mode": mode,
                "topic_scores": {},
                "matched_topics": [],
                "best_topic": "",
                "best_topic_label": "",
                "best_score": 0.0,
                "reason_codes": ["REDDIT_EMBEDDING_EMPTY_TEXT"],
            },
        )
        (passed if mode == "shadow" else dropped).append(item)

    if not nonempty_items:
        return passed, dropped

    topic_vectors = _embed_texts(
        active_client,
        [str(topic["description"]) for topic in topics],
    )
    item_vectors = _embed_texts(active_client, item_texts)
    for item, item_vector in zip(nonempty_items, item_vectors):
        scores = {
            str(topic["id"]): _similarity(item_vector, topic_vector)
            for topic, topic_vector in zip(topics, topic_vectors)
        }
        best_topic = max(
            topics,
            key=lambda topic: scores[str(topic["id"])],
        )
        best_topic_id = str(best_topic["id"])
        best_score = scores[best_topic_id]
        matched = [
            str(topic["id"])
            for topic in topics
            if scores[str(topic["id"])] >= float(topic["threshold"])
        ]
        threshold_passed = bool(matched)
        decision = (
            "pass"
            if threshold_passed
            else ("shadow_drop" if mode == "shadow" else "drop")
        )
        append_reddit_filter_stage(
            item,
            {
                "stage": "embedding",
                "decision": decision,
                "mode": mode,
                "topic_scores": {
                    topic_id: round(score, 4)
                    for topic_id, score in scores.items()
                },
                "topic_thresholds": {
                    str(topic["id"]): round(float(topic["threshold"]), 4)
                    for topic in topics
                },
                "matched_topics": matched,
                "best_topic": best_topic_id,
                "best_topic_label": str(best_topic["label"]),
                "best_score": round(best_score, 4),
                "reason_codes": [
                    "REDDIT_EMBEDDING_THRESHOLD_PASSED"
                    if threshold_passed
                    else "REDDIT_EMBEDDING_BELOW_THRESHOLD"
                ],
            },
        )
        (dropped if decision == "drop" else passed).append(item)
    return passed, dropped
