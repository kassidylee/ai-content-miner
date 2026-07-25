"""GitHub 仓库筛选的第二层关键词 Embedding 相关度。"""

from __future__ import annotations

import math
import re
from numbers import Real
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import config
from analyzer.github_common import append_github_filter_stage
from utils.embedding import EmbeddingError, create_client, encode


class GithubEmbeddingError(RuntimeError):
    """GitHub Embedding 配置、请求或向量格式错误。"""


def _clean(value: object) -> str:
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _raw(item: Dict) -> Dict:
    value = item.get("raw", {})
    return value if isinstance(value, dict) else {}


def build_github_embedding_text(item: Dict) -> str:
    """组合仓库名、描述、README、Topics 和语言，不加入热度或作者。"""
    raw = _raw(item)
    sections: List[str] = []
    full_name = _clean(raw.get("full_name") or item.get("title"))
    if full_name:
        sections.append(f"仓库：{full_name}")
    description = _clean(raw.get("description"))
    if description:
        sections.append(f"描述：{description}")
    topics = raw.get("topics", [])
    if isinstance(topics, list):
        normalized_topics = [
            _clean(topic) for topic in topics if _clean(topic)
        ]
        if normalized_topics:
            sections.append(f"Topics：{', '.join(normalized_topics[:20])}")
    language = _clean(raw.get("language"))
    if language:
        sections.append(f"主要语言：{language}")
    readme = _clean(raw.get("readme"))
    if readme:
        sections.append(f"README：{readme}")
    limit = int(config.GITHUB_EMBEDDING_MAX_CHARS)
    return "\n\n".join(sections)[:limit].strip()


def cosine_similarity(
    vector_a: Sequence[Real],
    vector_b: Sequence[Real],
) -> float:
    if len(vector_a) != len(vector_b):
        raise GithubEmbeddingError("GitHub Embedding 向量维度不一致")
    if not vector_a:
        return 0.0
    if any(not isinstance(value, Real) for value in vector_a) or any(
        not isinstance(value, Real) for value in vector_b
    ):
        raise GithubEmbeddingError("GitHub Embedding 向量包含非数值元素")
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


def _keywords() -> List[str]:
    configured = getattr(config, "SEARCH_KEYWORDS", [])
    if not isinstance(configured, list):
        raise GithubEmbeddingError("SEARCH_KEYWORDS 必须是列表")
    keywords: List[str] = []
    seen = set()
    for value in configured:
        keyword = _clean(value)
        normalized = keyword.casefold()
        if keyword and normalized not in seen:
            seen.add(normalized)
            keywords.append(keyword)
    if not keywords:
        raise GithubEmbeddingError("GitHub Embedding 至少需要一个搜索关键词")
    return keywords


def validate_github_embedding_config(require_credentials: bool = True) -> None:
    mode = str(config.GITHUB_EMBEDDING_FILTER_MODE).strip().casefold()
    if mode not in {"shadow", "enforce"}:
        raise GithubEmbeddingError(
            "GITHUB_EMBEDDING_FILTER_MODE 只能是 shadow 或 enforce"
        )
    if not str(config.GITHUB_EMBEDDING_MODEL).strip():
        raise GithubEmbeddingError("GITHUB_EMBEDDING_MODEL 不能为空")
    if require_credentials:
        api_key = str(config.GITHUB_EMBEDDING_API_KEY or "").strip()
        if not api_key:
            raise GithubEmbeddingError("GITHUB_EMBEDDING_API_KEY 未配置")
        base_url = str(config.GITHUB_EMBEDDING_BASE_URL or "").strip()
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise GithubEmbeddingError(
                "GITHUB_EMBEDDING_BASE_URL 必须是有效的 http/https URL"
            )
    if (
        not isinstance(config.GITHUB_EMBEDDING_BATCH_SIZE, int)
        or config.GITHUB_EMBEDDING_BATCH_SIZE <= 0
    ):
        raise GithubEmbeddingError(
            "GITHUB_EMBEDDING_BATCH_SIZE 必须是正整数"
        )
    if (
        not isinstance(config.GITHUB_EMBEDDING_MAX_CHARS, int)
        or config.GITHUB_EMBEDDING_MAX_CHARS <= 0
    ):
        raise GithubEmbeddingError(
            "GITHUB_EMBEDDING_MAX_CHARS 必须是正整数"
        )
    if (
        not isinstance(config.GITHUB_EMBEDDING_TIMEOUT_SECONDS, (int, float))
        or config.GITHUB_EMBEDDING_TIMEOUT_SECONDS <= 0
    ):
        raise GithubEmbeddingError(
            "GITHUB_EMBEDDING_TIMEOUT_SECONDS 必须大于 0"
        )
    if (
        not isinstance(config.GITHUB_EMBEDDING_MAX_RETRIES, int)
        or config.GITHUB_EMBEDDING_MAX_RETRIES < 0
    ):
        raise GithubEmbeddingError(
            "GITHUB_EMBEDDING_MAX_RETRIES 必须是非负整数"
        )
    threshold = config.GITHUB_EMBEDDING_THRESHOLD
    if not isinstance(threshold, Real) or not 0 <= float(threshold) <= 1:
        raise GithubEmbeddingError(
            "GITHUB_EMBEDDING_THRESHOLD 必须在 0 到 1 之间"
        )
    _keywords()


def _embed_texts(client: object, texts: Sequence[str]) -> List[List[float]]:
    try:
        return encode(
            texts,
            client=client,
            model=config.GITHUB_EMBEDDING_MODEL,
            batch_size=config.GITHUB_EMBEDDING_BATCH_SIZE,
        )
    except EmbeddingError as exc:
        raise GithubEmbeddingError(str(exc)) from exc

def probe_github_embedding_service(client: Optional[object] = None) -> int:
    """请求一个关键词向量，返回维度，用于启动前连通性检查。"""
    validate_github_embedding_config(require_credentials=client is None)
    active_client = client or create_client(
        api_key=config.GITHUB_EMBEDDING_API_KEY,
        base_url=config.GITHUB_EMBEDDING_BASE_URL,
    )
    vectors = _embed_texts(active_client, [_keywords()[0]])
    if not vectors or not vectors[0]:
        raise GithubEmbeddingError("GitHub Embedding 探测返回了空向量")
    return len(vectors[0])


def apply_github_embedding_filter(
    items: Iterable[Dict],
    client: Optional[object] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """比较每个仓库的语义内容与全部搜索关键词。"""
    candidates = list(items)
    if not candidates:
        return [], []
    validate_github_embedding_config(require_credentials=client is None)
    mode = str(config.GITHUB_EMBEDDING_FILTER_MODE).strip().casefold()
    threshold = float(config.GITHUB_EMBEDDING_THRESHOLD)
    keywords = _keywords()
    if client is None:
        client = create_client(
            api_key=config.GITHUB_EMBEDDING_API_KEY,
            base_url=config.GITHUB_EMBEDDING_BASE_URL,
        )

    passed: List[Dict] = []
    dropped: List[Dict] = []
    nonempty_items: List[Dict] = []
    texts: List[str] = []
    for item in candidates:
        text = build_github_embedding_text(item)
        if text:
            nonempty_items.append(item)
            texts.append(text)
            continue
        decision = "shadow_drop" if mode == "shadow" else "drop"
        append_github_filter_stage(
            item,
            {
                "stage": "embedding",
                "decision": decision,
                "mode": mode,
                "keyword_scores": {},
                "matched_keywords": [],
                "best_keyword": "",
                "best_score": 0.0,
                "threshold": threshold,
                "reason_codes": ["GITHUB_EMBEDDING_EMPTY_TEXT"],
            },
        )
        (passed if mode == "shadow" else dropped).append(item)

    if not nonempty_items:
        return passed, dropped

    keyword_vectors = _embed_texts(client, keywords)
    item_vectors = _embed_texts(client, texts)
    for item, item_vector in zip(nonempty_items, item_vectors):
        scores = {
            keyword: cosine_similarity(item_vector, keyword_vector)
            for keyword, keyword_vector in zip(keywords, keyword_vectors)
        }
        best_keyword = max(keywords, key=lambda keyword: scores[keyword])
        best_score = scores[best_keyword]
        matched = [
            keyword for keyword in keywords if scores[keyword] >= threshold
        ]
        threshold_passed = best_score >= threshold
        decision = (
            "pass"
            if threshold_passed
            else ("shadow_drop" if mode == "shadow" else "drop")
        )
        append_github_filter_stage(
            item,
            {
                "stage": "embedding",
                "decision": decision,
                "mode": mode,
                "keyword_scores": {
                    keyword: round(score, 4)
                    for keyword, score in scores.items()
                },
                "matched_keywords": matched,
                "best_keyword": best_keyword,
                "best_score": round(best_score, 4),
                "threshold": round(threshold, 4),
                "reason_codes": [
                    "GITHUB_EMBEDDING_THRESHOLD_PASSED"
                    if threshold_passed
                    else "GITHUB_EMBEDDING_BELOW_THRESHOLD"
                ],
            },
        )
        (dropped if decision == "drop" else passed).append(item)
    return passed, dropped
