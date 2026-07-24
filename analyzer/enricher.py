"""为保留内容生成极简标题、摘要和分层标签。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import config


class EnrichmentConfigError(ValueError):
    """摘要或标签配置错误。"""


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _read_field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _taxonomy_index() -> Dict[str, Dict[str, object]]:
    taxonomy = getattr(config, "TAG_TAXONOMY", [])
    if not isinstance(taxonomy, list) or not taxonomy:
        raise EnrichmentConfigError("TAG_TAXONOMY 必须是非空列表")

    index: Dict[str, Dict[str, object]] = {}
    for entry in taxonomy:
        if not isinstance(entry, dict):
            raise EnrichmentConfigError("标签定义必须是字典")
        tag_id = _clean_text(entry.get("id"))
        label = _clean_text(entry.get("label"))
        level = entry.get("level")
        parent_id = entry.get("parent_id")
        if (
            not tag_id
            or tag_id in index
            or not label
            or not isinstance(level, int)
            or level not in {1, 2}
        ):
            raise EnrichmentConfigError("一级或二级标签定义无效")
        index[tag_id] = {
            "id": tag_id,
            "label": label,
            "level": level,
            "parent_id": str(parent_id) if parent_id else None,
        }

    for tag in index.values():
        parent_id = tag["parent_id"]
        if parent_id and parent_id not in index:
            raise EnrichmentConfigError(f"标签 {tag['id']} 的父标签不存在")
    return index


def validate_enrichment_config() -> None:
    """在采集前校验摘要长度和受控标签树。"""
    _taxonomy_index()
    positive_integer_names = (
        "ENRICHER_TITLE_MAX_CHARS",
        "ENRICHER_ABSTRACT_MAX_CHARS",
        "ENRICHER_INPUT_MAX_CHARS",
        "ENRICHER_LONG_MESSAGE_CHARS",
        "ENRICHER_ENTITY_LIMIT",
        "ENRICHER_MAX_TOKENS",
    )
    for name in positive_integer_names:
        value = getattr(config, name, 0)
        if not isinstance(value, int) or value <= 0:
            raise EnrichmentConfigError(f"{name} 必须是正整数")
    temperature = getattr(config, "ENRICHER_TEMPERATURE", None)
    if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise EnrichmentConfigError("ENRICHER_TEMPERATURE 必须在 0 到 2 之间")


def _embedding_tag_ids(item: Dict) -> List[str]:
    topic_to_tag = {
        str(topic.get("id", "") or ""): str(topic.get("tag_id", "") or "")
        for topic in getattr(config, "INTEREST_TOPICS", [])
        if isinstance(topic, dict)
    }
    for stage in reversed(item.get("filter_metadata", {}).get("stages", [])):
        if not isinstance(stage, dict) or stage.get("stage") != "embedding":
            continue
        matched = stage.get("matched_topics", [])
        if not isinstance(matched, list):
            return []
        return [
            topic_to_tag.get(str(topic_id), "")
            for topic_id in matched
            if topic_to_tag.get(str(topic_id))
        ]
    return []


def _content_form_tag_ids(item: Dict) -> List[str]:
    forms: List[str] = []
    for entry in item.get("referenced_urls", []):
        if not isinstance(entry, dict):
            continue
        parsed = urlparse(str(entry.get("url", "") or ""))
        domain = parsed.netloc.casefold().removeprefix("www.")
        if domain == "arxiv.org" or domain.endswith(".arxiv.org"):
            if "paper" not in forms:
                forms.append("paper")
        if domain == "github.com" or domain.endswith(".github.com"):
            if "project-release" not in forms:
                forms.append("project-release")

    if not forms:
        threshold = int(getattr(config, "ENRICHER_LONG_MESSAGE_CHARS", 500))
        form = (
            "long-message"
            if len(_clean_text(item.get("content"))) >= threshold
            else "short-message"
        )
        forms.append(form)
    return forms


def _source_text(item: Dict) -> str:
    sections = [
        _clean_text(item.get("content")),
        _clean_text(item.get("quoted_content")),
    ]
    for entry in item.get("referenced_urls", []):
        if isinstance(entry, dict):
            sections.append(_clean_text(entry.get("label")))
            sections.append(_clean_text(entry.get("url")))
    limit = int(getattr(config, "ENRICHER_INPUT_MAX_CHARS", 6000))
    return "\n".join(section for section in sections if section)[:limit]


def _fallback_title(item: Dict) -> str:
    metadata = item.get("platform_metadata", {})
    has_native_title = (
        isinstance(metadata, dict) and metadata.get("has_native_title") is True
    )
    current_title = _clean_text(item.get("title"))
    if has_native_title and current_title and current_title != "无标题":
        return current_title
    content = _clean_text(item.get("content"))
    limit = int(getattr(config, "ENRICHER_TITLE_MAX_CHARS", 48))
    return (content or current_title or "无标题")[:limit].rstrip("，,。.!！?")


def _limit_abstract(value: object) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+", text)
        if sentence.strip()
    ]
    concise = " ".join(sentences[:2]) if sentences else text
    limit = int(getattr(config, "ENRICHER_ABSTRACT_MAX_CHARS", 180))
    return concise[:limit].strip()


def _fallback_abstract(item: Dict) -> str:
    text = _clean_text(item.get("content"))
    if not text:
        return ""
    first_sentence = re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+", text)[0]
    limit = int(getattr(config, "ENRICHER_ABSTRACT_MAX_CHARS", 180))
    return first_sentence[:limit].strip()


def _extract_json(response: object) -> Dict[str, object]:
    choices = _read_field(response, "choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("摘要 API 未返回 choices")
    message = _read_field(choices[0], "message")
    raw = _clean_text(_read_field(message, "content"))
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError("摘要 API 未返回 JSON")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("摘要 API 返回的 JSON 不是对象")
    return parsed


def _tag_dict(
    tag: Dict[str, object],
    source: str,
) -> Dict[str, object]:
    return {
        "id": tag["id"],
        "label": tag["label"],
        "level": tag["level"],
        "parent_id": tag["parent_id"],
        "source": source,
    }


def _build_tags(
    item: Dict,
    taxonomy: Dict[str, Dict[str, object]],
    model_tag_ids: Sequence[str],
    entities: Sequence[str],
    source_text: str,
) -> Tuple[List[Dict[str, object]], List[str]]:
    content_form_ids = _content_form_tag_ids(item)
    deterministic_ids = content_form_ids + _embedding_tag_ids(item)
    selected_ids: List[str] = []
    sources: Dict[str, str] = {}
    for tag_id in deterministic_ids:
        if tag_id in taxonomy and tag_id not in selected_ids:
            selected_ids.append(tag_id)
            sources[tag_id] = (
                "content_rule" if tag_id in content_form_ids else "embedding"
            )
    for tag_id in model_tag_ids:
        if tag_id in taxonomy and tag_id not in selected_ids:
            selected_ids.append(tag_id)
            sources[tag_id] = "model"

    for tag_id in list(selected_ids):
        parent_id = taxonomy[tag_id].get("parent_id")
        if parent_id and parent_id not in selected_ids:
            selected_ids.append(str(parent_id))
            sources[str(parent_id)] = "taxonomy"

    tags = [
        _tag_dict(tag, sources.get(tag_id, "taxonomy"))
        for tag_id, tag in taxonomy.items()
        if tag_id in selected_ids
    ]

    topic_parent = next(
        (
            tag_id
            for tag_id in selected_ids
            if taxonomy[tag_id]["level"] == 2
            and taxonomy[tag_id]["parent_id"] == "ai"
        ),
        "ai",
    )
    normalized_source = source_text.casefold()
    accepted_entities: List[str] = []
    entity_limit = int(getattr(config, "ENRICHER_ENTITY_LIMIT", 5))
    for entity in entities:
        label = _clean_text(entity)
        if (
            not label
            or label.casefold() not in normalized_source
            or label.casefold() in {value.casefold() for value in accepted_entities}
        ):
            continue
        accepted_entities.append(label)
        if "ai" in taxonomy and not any(tag["id"] == "ai" for tag in tags):
            tags.insert(0, _tag_dict(taxonomy["ai"], "taxonomy"))
        digest = hashlib.sha1(label.casefold().encode("utf-8")).hexdigest()[:12]
        tags.append(
            {
                "id": f"entity-{digest}",
                "label": label,
                "level": 3,
                "parent_id": topic_parent,
                "source": "model_entity",
            }
        )
        if len(accepted_entities) >= entity_limit:
            break
    return tags, accepted_entities


def _prompt(item: Dict, taxonomy: Dict[str, Dict[str, object]]) -> str:
    allowed_tags = [
        {
            "id": tag["id"],
            "label": tag["label"],
            "level": tag["level"],
        }
        for tag in taxonomy.values()
        if tag["parent_id"] == "ai"
    ]
    return f"""请把下面的社交平台内容整理为极简结构化信息。

要求：
1. title 是不超过 {config.ENRICHER_TITLE_MAX_CHARS} 个字符的事实性标题。
2. abstract 只用一到两句话说明主要内容，不评价、不扩写、不添加原文信息。
3. tag_ids 只能从允许的技术标签 ID 中选择。
4. entities 只列出原文或链接文字中明确出现的项目、论文、模型或产品名。
5. 只返回 JSON，不要返回 Markdown。

允许的技术标签：
{json.dumps(allowed_tags, ensure_ascii=False)}

返回结构：
{{
  "title": "极简标题",
  "abstract": "一到两句话摘要",
  "tag_ids": ["标签 ID"],
  "entities": ["原文中出现的实体"]
}}

原始内容：
{_source_text(item)}"""


def _fallback_result(
    item: Dict,
    taxonomy: Dict[str, Dict[str, object]],
    error_type: str = "",
) -> Dict:
    source_text = _source_text(item)
    tags, entities = _build_tags(item, taxonomy, [], [], source_text)
    item["title"] = _fallback_title(item)
    item["abstract"] = _fallback_abstract(item)
    item["tags"] = tags
    item["entities"] = entities
    item["enrichment_metadata"] = {
        "status": "fallback",
        "error_type": error_type,
    }
    return item


def enrich_item(
    item: Dict,
    client: object,
    taxonomy: Optional[Dict[str, Dict[str, object]]] = None,
) -> Dict:
    """单次模型调用同时生成标题、摘要、受控标签和实体。"""
    selected_taxonomy = taxonomy or _taxonomy_index()
    source_text = _source_text(item)
    if not source_text:
        return _fallback_result(item, selected_taxonomy, "EmptyContent")

    try:
        response = client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": "你只做忠实、简洁的信息整理，并返回合法 JSON。",
                },
                {"role": "user", "content": _prompt(item, selected_taxonomy)},
            ],
            temperature=float(getattr(config, "ENRICHER_TEMPERATURE", 0.1)),
            max_tokens=int(getattr(config, "ENRICHER_MAX_TOKENS", 600)),
        )
        parsed = _extract_json(response)
        raw_tag_ids = parsed.get("tag_ids", [])
        raw_entities = parsed.get("entities", [])
        model_tag_ids = (
            [str(tag_id) for tag_id in raw_tag_ids]
            if isinstance(raw_tag_ids, list)
            else []
        )
        entities = (
            [str(entity) for entity in raw_entities]
            if isinstance(raw_entities, list)
            else []
        )
        tags, accepted_entities = _build_tags(
            item,
            selected_taxonomy,
            model_tag_ids,
            entities,
            source_text,
        )

        metadata = item.get("platform_metadata", {})
        has_native_title = (
            isinstance(metadata, dict)
            and metadata.get("has_native_title") is True
        )
        generated_title = _clean_text(parsed.get("title"))
        title_limit = int(getattr(config, "ENRICHER_TITLE_MAX_CHARS", 48))
        if has_native_title:
            title = _fallback_title(item)
        else:
            title = generated_title[:title_limit] or _fallback_title(item)
        abstract = _limit_abstract(parsed.get("abstract")) or _fallback_abstract(
            item
        )

        item["title"] = title
        item["abstract"] = abstract
        item["tags"] = tags
        item["entities"] = accepted_entities
        item["enrichment_metadata"] = {
            "status": "generated",
            "error_type": "",
        }
        return item
    except Exception as exc:
        return _fallback_result(
            item,
            selected_taxonomy,
            type(exc).__name__,
        )


def enrich_items(
    items: Iterable[Dict],
    client: Optional[object] = None,
) -> List[Dict]:
    """只对调用方传入的最终保留项执行信息整理。"""
    candidates = list(items)
    if not candidates:
        return []
    taxonomy = _taxonomy_index()

    if client is None:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)
        except Exception as exc:
            return [
                _fallback_result(item, taxonomy, type(exc).__name__)
                for item in candidates
            ]
    return [enrich_item(item, client, taxonomy) for item in candidates]
