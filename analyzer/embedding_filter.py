"""第二层 Embedding 语义筛选。"""

from __future__ import annotations

import math
import re
from numbers import Real
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import config
from analyzer.filter import append_filter_stage


class EmbeddingFilterError(RuntimeError):
    """Embedding 配置、请求或向量格式错误。"""


def _clean_text(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def build_embedding_text(item: Dict, max_chars: Optional[int] = None) -> str:
    """构造语义输入，不修改原始内容。"""
    limit = max_chars or int(getattr(config, "EMBEDDING_MAX_CHARS", 6000))
    sections: List[str] = []

    content = _clean_text(item.get("content"))
    if content:
        sections.append(content)

    quoted_content = _clean_text(item.get("quoted_content"))
    if quoted_content:
        sections.append(f"引用内容：{quoted_content}")

    link_labels: List[str] = []
    for entry in item.get("referenced_urls", []):
        if not isinstance(entry, dict):
            continue
        label = _clean_text(entry.get("label") or entry.get("domain"))
        domain = _clean_text(entry.get("domain"))
        value = label or domain
        if value and value not in link_labels:
            link_labels.append(value)
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

    return "\n\n".join(sections)[:limit].strip()


def cosine_similarity(vector_a: Sequence[Real], vector_b: Sequence[Real]) -> float:
    """使用标准库计算余弦相似度。"""
    if len(vector_a) != len(vector_b):
        raise EmbeddingFilterError("Embedding 向量维度不一致")
    if not vector_a:
        return 0.0
    if any(not isinstance(value, Real) for value in (*vector_a, *vector_b)):
        raise EmbeddingFilterError("Embedding 向量包含非数值元素")

    norm_a = math.sqrt(sum(float(value) ** 2 for value in vector_a))
    norm_b = math.sqrt(sum(float(value) ** 2 for value in vector_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    dot_product = sum(
        float(value_a) * float(value_b)
        for value_a, value_b in zip(vector_a, vector_b)
    )
    return dot_product / (norm_a * norm_b)


def _read_field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _validate_topics(topics: object) -> List[Dict[str, object]]:
    if not isinstance(topics, list) or not topics:
        raise EmbeddingFilterError("INTEREST_TOPICS 必须是非空列表")

    normalized: List[Dict[str, object]] = []
    seen_ids = set()
    for topic in topics:
        if not isinstance(topic, dict):
            raise EmbeddingFilterError("兴趣主题必须是字典")
        topic_id = str(topic.get("id", "") or "").strip()
        label = str(topic.get("label", "") or "").strip()
        description = str(topic.get("description", "") or "").strip()
        tag_id = str(topic.get("tag_id", "") or "").strip()
        threshold = topic.get("threshold")
        if not topic_id or topic_id in seen_ids:
            raise EmbeddingFilterError("兴趣主题 ID 为空或重复")
        if not label or not description or not tag_id:
            raise EmbeddingFilterError(f"兴趣主题 {topic_id} 配置不完整")
        if not isinstance(threshold, Real) or not 0 <= float(threshold) <= 1:
            raise EmbeddingFilterError(f"兴趣主题 {topic_id} 阈值无效")
        seen_ids.add(topic_id)
        normalized.append(
            {
                "id": topic_id,
                "label": label,
                "description": description,
                "threshold": float(threshold),
                "tag_id": tag_id,
            }
        )
    return normalized


def _embed_texts(
    client: object,
    texts: Sequence[str],
    model: str,
    batch_size: int,
) -> List[List[float]]:
    """批量请求向量，并按响应 index 恢复输入顺序。"""
    vectors: List[List[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        try:
            response = client.embeddings.create(model=model, input=batch)
        except Exception as exc:
            raise EmbeddingFilterError(
                f"Embedding API 请求失败：{type(exc).__name__}"
            ) from exc

        data = _read_field(response, "data")
        if not isinstance(data, list) or len(data) != len(batch):
            raise EmbeddingFilterError("Embedding API 返回数量与输入不一致")

        ordered: List[Optional[List[float]]] = [None] * len(batch)
        for entry in data:
            index = _read_field(entry, "index")
            vector = _read_field(entry, "embedding")
            if not isinstance(index, int) or not 0 <= index < len(batch):
                raise EmbeddingFilterError("Embedding API 返回了无效 index")
            if ordered[index] is not None:
                raise EmbeddingFilterError("Embedding API 返回了重复 index")
            if not isinstance(vector, list) or any(
                not isinstance(value, Real) for value in vector
            ):
                raise EmbeddingFilterError("Embedding API 返回了无效向量")
            ordered[index] = [float(value) for value in vector]

        if any(vector is None for vector in ordered):
            raise EmbeddingFilterError("Embedding API 返回的 index 不完整")
        vectors.extend(vector for vector in ordered if vector is not None)
    return vectors


def apply_embedding_filters(
    items: Iterable[Dict],
    client: Optional[object] = None,
    topics: Optional[List[Dict[str, object]]] = None,
    mode: Optional[str] = None,
    model: Optional[str] = None,
    batch_size: Optional[int] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """批量执行第二层筛选，返回继续处理项和正式删除项。"""
    candidates = list(items)
    if not candidates:
        return [], []

    selected_mode = str(
        mode or getattr(config, "EMBEDDING_FILTER_MODE", "shadow")
    ).strip().lower()
    if selected_mode not in {"shadow", "enforce"}:
        raise EmbeddingFilterError("EMBEDDING_FILTER_MODE 只能是 shadow 或 enforce")
    selected_model = str(
        model or getattr(config, "EMBEDDING_MODEL", "")
    ).strip()
    if not selected_model:
        raise EmbeddingFilterError("EMBEDDING_MODEL 未配置")
    selected_batch_size = batch_size or int(
        getattr(config, "EMBEDDING_BATCH_SIZE", 50)
    )
    if selected_batch_size <= 0:
        raise EmbeddingFilterError("EMBEDDING_BATCH_SIZE 必须大于 0")

    selected_topics = _validate_topics(
        topics if topics is not None else getattr(config, "INTEREST_TOPICS", [])
    )
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

    passed: List[Dict] = []
    dropped: List[Dict] = []
    nonempty_items: List[Dict] = []
    item_texts: List[str] = []
    for item in candidates:
        text = build_embedding_text(item)
        if text:
            nonempty_items.append(item)
            item_texts.append(text)
            continue
        decision = "shadow_drop" if selected_mode == "shadow" else "drop"
        result = {
            "stage": "embedding",
            "decision": decision,
            "mode": selected_mode,
            "topic_scores": {},
            "matched_topics": [],
            "best_topic": "",
            "best_topic_label": "",
            "best_score": 0.0,
            "best_topic_threshold": None,
            "reason_codes": ["EMBEDDING_EMPTY_TEXT"],
        }
        append_filter_stage(item, result)
        (passed if selected_mode == "shadow" else dropped).append(item)

    if not nonempty_items:
        return passed, dropped

    topic_vectors = _embed_texts(
        client,
        [str(topic["description"]) for topic in selected_topics],
        selected_model,
        selected_batch_size,
    )
    item_vectors = _embed_texts(
        client, item_texts, selected_model, selected_batch_size
    )

    for item, item_vector in zip(nonempty_items, item_vectors):
        raw_scores = {
            str(topic["id"]): cosine_similarity(item_vector, topic_vector)
            for topic, topic_vector in zip(selected_topics, topic_vectors)
        }
        best_topic = max(
            selected_topics,
            key=lambda topic: raw_scores[str(topic["id"])],
        )
        matched_topics = [
            str(topic["id"])
            for topic in selected_topics
            if raw_scores[str(topic["id"])] >= float(topic["threshold"])
        ]
        decision = (
            "pass"
            if matched_topics
            else ("shadow_drop" if selected_mode == "shadow" else "drop")
        )
        reason_codes = (
            ["EMBEDDING_THRESHOLD_PASSED"]
            if matched_topics
            else ["EMBEDDING_BELOW_ALL_TOPIC_THRESHOLDS"]
        )
        result = {
            "stage": "embedding",
            "decision": decision,
            "mode": selected_mode,
            "topic_scores": {
                topic_id: round(score, 4)
                for topic_id, score in raw_scores.items()
            },
            "topic_thresholds": {
                str(topic["id"]): round(float(topic["threshold"]), 4)
                for topic in selected_topics
            },
            "matched_topics": matched_topics,
            "best_topic": str(best_topic["id"]),
            "best_topic_label": str(best_topic["label"]),
            "best_score": round(raw_scores[str(best_topic["id"])], 4),
            "best_topic_threshold": round(float(best_topic["threshold"]), 4),
            "reason_codes": reason_codes,
        }
        append_filter_stage(item, result)
        (dropped if decision == "drop" else passed).append(item)
    return passed, dropped
