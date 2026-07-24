"""Twitter 新流程的第二层 Embedding 语义筛选。"""

from __future__ import annotations

import math
import re
from numbers import Real
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import config
from analyzer.twitter_common import append_twitter_filter_stage


class TwitterEmbeddingError(RuntimeError):
    """Twitter Embedding 配置、请求或向量格式错误。"""


def _clean_text(value: object) -> str:
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def build_twitter_embedding_text(item: Dict) -> str:
    """组合正文、引用、展开链接和 hashtag，不加入互动量或用户名。"""
    sections: List[str] = []
    content = _clean_text(item.get("content"))
    if content:
        sections.append(content)
    quoted = _clean_text(item.get("quoted_content"))
    if quoted:
        sections.append(f"引用内容：{quoted}")

    link_labels: List[str] = []
    for entry in item.get("referenced_urls", []):
        if not isinstance(entry, dict):
            continue
        label = _clean_text(entry.get("label") or entry.get("domain"))
        if label and label not in link_labels:
            link_labels.append(label)
    if link_labels:
        sections.append(f"相关链接：{', '.join(link_labels)}")

    metadata = item.get("platform_metadata", {})
    hashtags: List[str] = []
    if isinstance(metadata, dict):
        for tag in metadata.get("hashtags", []):
            normalized = _clean_text(tag).lstrip("#")
            if len(normalized) >= 2 and normalized not in hashtags:
                hashtags.append(normalized)
    if hashtags:
        sections.append(f"主题词：{', '.join(hashtags[:8])}")

    limit = int(config.TWITTER_EMBEDDING_MAX_CHARS)
    return "\n\n".join(sections)[:limit].strip()


def cosine_similarity(
    vector_a: Sequence[Real],
    vector_b: Sequence[Real],
) -> float:
    if len(vector_a) != len(vector_b):
        raise TwitterEmbeddingError("Embedding 向量维度不一致")
    if not vector_a:
        return 0.0
    if any(not isinstance(value, Real) for value in vector_a) or any(
        not isinstance(value, Real) for value in vector_b
    ):
        raise TwitterEmbeddingError("Embedding 向量包含非数值元素")
    norm_a = math.sqrt(sum(float(value) ** 2 for value in vector_a))
    norm_b = math.sqrt(sum(float(value) ** 2 for value in vector_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    dot = sum(
        float(value_a) * float(value_b)
        for value_a, value_b in zip(vector_a, vector_b)
    )
    return dot / (norm_a * norm_b)


def _field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _topics() -> List[Dict[str, object]]:
    topics = config.TWITTER_INTEREST_TOPICS
    if not isinstance(topics, list) or not topics:
        raise TwitterEmbeddingError(
            "TWITTER_INTEREST_TOPICS 必须是非空列表"
        )
    normalized: List[Dict[str, object]] = []
    seen = set()
    for topic in topics:
        if not isinstance(topic, dict):
            raise TwitterEmbeddingError("Twitter 兴趣主题必须是字典")
        topic_id = str(topic.get("id", "") or "").strip()
        threshold = topic.get("threshold")
        if (
            not topic_id
            or topic_id in seen
            or not str(topic.get("label", "") or "").strip()
            or not str(topic.get("description", "") or "").strip()
            or not str(topic.get("tag_id", "") or "").strip()
            or not isinstance(threshold, Real)
            or not 0 <= float(threshold) <= 1
        ):
            raise TwitterEmbeddingError("Twitter 兴趣主题配置无效")
        seen.add(topic_id)
        normalized.append(
            {
                "id": topic_id,
                "label": str(topic["label"]).strip(),
                "description": str(topic["description"]).strip(),
                "threshold": float(threshold),
                "tag_id": str(topic["tag_id"]).strip(),
            }
        )
    return normalized


def validate_twitter_embedding_config() -> None:
    mode = str(config.TWITTER_EMBEDDING_FILTER_MODE).strip().casefold()
    if mode not in {"shadow", "enforce"}:
        raise TwitterEmbeddingError(
            "TWITTER_EMBEDDING_FILTER_MODE 只能是 shadow 或 enforce"
        )
    if not str(config.TWITTER_EMBEDDING_MODEL).strip():
        raise TwitterEmbeddingError("TWITTER_EMBEDDING_MODEL 不能为空")
    if (
        not isinstance(config.TWITTER_EMBEDDING_BATCH_SIZE, int)
        or config.TWITTER_EMBEDDING_BATCH_SIZE <= 0
    ):
        raise TwitterEmbeddingError(
            "TWITTER_EMBEDDING_BATCH_SIZE 必须是正整数"
        )
    if (
        not isinstance(config.TWITTER_EMBEDDING_MAX_CHARS, int)
        or config.TWITTER_EMBEDDING_MAX_CHARS <= 0
    ):
        raise TwitterEmbeddingError(
            "TWITTER_EMBEDDING_MAX_CHARS 必须是正整数"
        )
    _topics()


def _embed_texts(
    client: object,
    texts: Sequence[str],
) -> List[List[float]]:
    vectors: List[List[float]] = []
    batch_size = int(config.TWITTER_EMBEDDING_BATCH_SIZE)
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        try:
            response = client.embeddings.create(
                model=config.TWITTER_EMBEDDING_MODEL,
                input=batch,
            )
        except Exception as exc:
            raise TwitterEmbeddingError(
                f"Embedding API 请求失败：{type(exc).__name__}"
            ) from exc

        data = _field(response, "data")
        if not isinstance(data, list) or len(data) != len(batch):
            raise TwitterEmbeddingError(
                "Embedding API 返回数量与输入不一致"
            )
        ordered: List[Optional[List[float]]] = [None] * len(batch)
        for entry in data:
            index = _field(entry, "index")
            vector = _field(entry, "embedding")
            if not isinstance(index, int) or not 0 <= index < len(batch):
                raise TwitterEmbeddingError(
                    "Embedding API 返回了无效 index"
                )
            if ordered[index] is not None:
                raise TwitterEmbeddingError(
                    "Embedding API 返回了重复 index"
                )
            if not isinstance(vector, list) or any(
                not isinstance(value, Real) for value in vector
            ):
                raise TwitterEmbeddingError(
                    "Embedding API 返回了无效向量"
                )
            ordered[index] = [float(value) for value in vector]
        if any(vector is None for vector in ordered):
            raise TwitterEmbeddingError(
                "Embedding API 返回的 index 不完整"
            )
        vectors.extend(vector for vector in ordered if vector is not None)
    return vectors


def apply_twitter_embedding_filter(
    items: Iterable[Dict],
    client: Optional[object] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """批量比较每条推文与所有兴趣主题。"""
    candidates = list(items)
    if not candidates:
        return [], []
    validate_twitter_embedding_config()
    mode = str(config.TWITTER_EMBEDDING_FILTER_MODE).strip().casefold()
    topics = _topics()
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

    passed: List[Dict] = []
    dropped: List[Dict] = []
    nonempty_items: List[Dict] = []
    texts: List[str] = []
    for item in candidates:
        text = build_twitter_embedding_text(item)
        if text:
            nonempty_items.append(item)
            texts.append(text)
            continue
        decision = "shadow_drop" if mode == "shadow" else "drop"
        append_twitter_filter_stage(
            item,
            {
                "stage": "embedding",
                "decision": decision,
                "mode": mode,
                "topic_scores": {},
                "matched_topics": [],
                "best_topic": "",
                "best_score": 0.0,
                "reason_codes": ["TWITTER_EMBEDDING_EMPTY_TEXT"],
            },
        )
        (passed if mode == "shadow" else dropped).append(item)

    if not nonempty_items:
        return passed, dropped

    topic_vectors = _embed_texts(
        client,
        [str(topic["description"]) for topic in topics],
    )
    item_vectors = _embed_texts(client, texts)
    for item, item_vector in zip(nonempty_items, item_vectors):
        raw_scores = {
            str(topic["id"]): cosine_similarity(item_vector, topic_vector)
            for topic, topic_vector in zip(topics, topic_vectors)
        }
        best_topic = max(
            topics,
            key=lambda topic: raw_scores[str(topic["id"])],
        )
        matched_topics = [
            str(topic["id"])
            for topic in topics
            if raw_scores[str(topic["id"])] >= float(topic["threshold"])
        ]
        best_topic_passed = (
            raw_scores[str(best_topic["id"])]
            >= float(best_topic["threshold"])
        )
        decision = (
            "pass"
            if best_topic_passed
            else ("shadow_drop" if mode == "shadow" else "drop")
        )
        append_twitter_filter_stage(
            item,
            {
                "stage": "embedding",
                "decision": decision,
                "mode": mode,
                "topic_scores": {
                    topic_id: round(score, 4)
                    for topic_id, score in raw_scores.items()
                },
                "topic_thresholds": {
                    str(topic["id"]): round(
                        float(topic["threshold"]),
                        4,
                    )
                    for topic in topics
                },
                "matched_topics": matched_topics,
                "best_topic": str(best_topic["id"]),
                "best_topic_label": str(best_topic["label"]),
                "best_score": round(
                    raw_scores[str(best_topic["id"])],
                    4,
                ),
                "best_topic_threshold": round(
                    float(best_topic["threshold"]),
                    4,
                ),
                "threshold": round(
                    float(best_topic["threshold"]),
                    4,
                ),
                "reason_codes": [
                    "TWITTER_EMBEDDING_THRESHOLD_PASSED"
                    if best_topic_passed
                    else "TWITTER_EMBEDDING_BELOW_THRESHOLD"
                ],
            },
        )
        (dropped if decision == "drop" else passed).append(item)
    return passed, dropped
