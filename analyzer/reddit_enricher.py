"""为通过筛选的 Reddit 帖子生成极简标题和摘要。"""

from __future__ import annotations

import json
import re
from typing import Dict, Iterable, List, Optional

import config


class RedditEnrichmentConfigError(ValueError):
    """Reddit 摘要配置无效。"""


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def validate_reddit_enrichment_config() -> None:
    for name in (
        "REDDIT_TITLE_MAX_CHARS",
        "REDDIT_ABSTRACT_MAX_CHARS",
        "REDDIT_ENRICHMENT_INPUT_MAX_CHARS",
        "REDDIT_ENRICHMENT_MAX_TOKENS",
        "REDDIT_ENRICHMENT_TIMEOUT_SECONDS",
    ):
        value = getattr(config, name, 0)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value <= 0
        ):
            raise RedditEnrichmentConfigError(f"{name} 必须大于 0")
    retries = getattr(config, "REDDIT_ENRICHMENT_MAX_RETRIES", None)
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise RedditEnrichmentConfigError(
            "REDDIT_ENRICHMENT_MAX_RETRIES 必须是非负整数"
        )


def _first_sentences(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    sentences = [
        sentence
        for sentence in re.split(
            r"(?<=[。！？!?])\s*|(?<=\.)\s+",
            text,
        )
        if sentence
    ]
    return " ".join(sentences[:2])[
        : int(config.REDDIT_ABSTRACT_MAX_CHARS)
    ].strip()


def _fallback(item: Dict, error: str) -> Dict:
    original_title = _clean(item.get("title")) or "Reddit 帖子"
    item["feed_title"] = original_title[
        : int(config.REDDIT_TITLE_MAX_CHARS)
    ]
    item["abstract"] = (
        _first_sentences(item.get("content"))
        or original_title[: int(config.REDDIT_ABSTRACT_MAX_CHARS)]
    )
    item["reddit_enrichment_metadata"] = {
        "status": "fallback",
        "error_type": error,
    }
    return item


def _response_json(response: object) -> Dict[str, object]:
    choices = _field(response, "choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("摘要 API 未返回 choices")
    message = _field(choices[0], "message")
    raw = _clean(_field(message, "content"))
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError("摘要 API 未返回 JSON")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("摘要 API 返回值不是对象")
    return parsed


def _prompt(item: Dict) -> str:
    title = _clean(item.get("title"))
    content = _clean(item.get("content"))[
        : int(config.REDDIT_ENRICHMENT_INPUT_MAX_CHARS)
    ]
    return f"""请把下面的 Reddit 技术帖子整理为极简中文信息。

要求：
1. title 不超过 {config.REDDIT_TITLE_MAX_CHARS} 个字符，保留模型、项目和硬件名称。
2. abstract 用一到两句话忠实概括帖子内容，不评价、不扩写。
3. 只返回 JSON：{{"title": "...", "abstract": "..."}}。

原始标题：
{title}

原始正文：
{content}"""


def enrich_reddit_items(
    items: Iterable[Dict],
    client: Optional[object] = None,
) -> List[Dict]:
    """逐条生成短摘要；服务失败时使用确定性本地降级。"""
    candidates = list(items)
    if not candidates:
        return []
    validate_reddit_enrichment_config()
    if client is None:
        from openai import OpenAI

        client = OpenAI(
            api_key=config.API_KEY,
            base_url=config.BASE_URL,
            timeout=float(config.REDDIT_ENRICHMENT_TIMEOUT_SECONDS),
            max_retries=int(config.REDDIT_ENRICHMENT_MAX_RETRIES),
        )

    for item in candidates:
        if not _clean(item.get("content")):
            _fallback(item, "EmptyContent")
            continue
        try:
            response = client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你只做忠实、简洁的信息整理，并返回合法 JSON。"
                        ),
                    },
                    {"role": "user", "content": _prompt(item)},
                ],
                temperature=float(config.REDDIT_ENRICHMENT_TEMPERATURE),
                max_tokens=int(config.REDDIT_ENRICHMENT_MAX_TOKENS),
            )
            parsed = _response_json(response)
            title = _clean(parsed.get("title"))
            abstract = _first_sentences(parsed.get("abstract"))
            item["feed_title"] = (
                title[: int(config.REDDIT_TITLE_MAX_CHARS)]
                or _clean(item.get("title"))[
                    : int(config.REDDIT_TITLE_MAX_CHARS)
                ]
                or "Reddit 帖子"
            )
            item["abstract"] = (
                abstract
                or _first_sentences(item.get("content"))
            )
            item["reddit_enrichment_metadata"] = {
                "status": "generated",
                "error_type": "",
            }
        except Exception as exc:
            _fallback(item, type(exc).__name__)
    return candidates
