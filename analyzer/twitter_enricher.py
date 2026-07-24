"""为通过筛选的 Twitter 内容生成极简摘要和分层标签。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import config


class TwitterEnrichmentConfigError(ValueError):
    """Twitter 摘要或标签配置错误。"""


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _taxonomy() -> Dict[str, Dict[str, object]]:
    entries = config.TWITTER_TAG_TAXONOMY
    if not isinstance(entries, list) or not entries:
        raise TwitterEnrichmentConfigError(
            "TWITTER_TAG_TAXONOMY 必须是非空列表"
        )
    index: Dict[str, Dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise TwitterEnrichmentConfigError("标签定义必须是字典")
        tag_id = _clean(entry.get("id"))
        label = _clean(entry.get("label"))
        level = entry.get("level")
        parent_id = entry.get("parent_id")
        if (
            not tag_id
            or tag_id in index
            or not label
            or not isinstance(level, int)
            or level not in {1, 2}
        ):
            raise TwitterEnrichmentConfigError("标签定义无效")
        index[tag_id] = {
            "id": tag_id,
            "label": label,
            "level": level,
            "parent_id": str(parent_id) if parent_id else None,
        }
    for tag in index.values():
        parent_id = tag["parent_id"]
        if parent_id and parent_id not in index:
            raise TwitterEnrichmentConfigError(
                f"标签 {tag['id']} 的父标签不存在"
            )
    return index


def validate_twitter_enrichment_config() -> None:
    _taxonomy()
    for name in (
        "TWITTER_TITLE_MAX_CHARS",
        "TWITTER_ABSTRACT_MAX_CHARS",
        "TWITTER_ENRICHMENT_INPUT_MAX_CHARS",
        "TWITTER_LONG_MESSAGE_CHARS",
        "TWITTER_ENTITY_LIMIT",
        "TWITTER_ENRICHMENT_MAX_TOKENS",
    ):
        value = getattr(config, name, 0)
        if not isinstance(value, int) or value <= 0:
            raise TwitterEnrichmentConfigError(f"{name} 必须是正整数")


def _source_text(item: Dict) -> str:
    sections = [
        _clean(item.get("content")),
        _clean(item.get("quoted_content")),
    ]
    for entry in item.get("referenced_urls", []):
        if isinstance(entry, dict):
            sections.append(_clean(entry.get("label")))
            sections.append(_clean(entry.get("url")))
    return "\n".join(
        section for section in sections if section
    )[: int(config.TWITTER_ENRICHMENT_INPUT_MAX_CHARS)]


def _content_form_ids(item: Dict) -> List[str]:
    forms: List[str] = []
    for entry in item.get("referenced_urls", []):
        if not isinstance(entry, dict):
            continue
        domain = urlparse(
            str(entry.get("url", "") or "")
        ).netloc.casefold().removeprefix("www.")
        if domain == "arxiv.org" and "paper" not in forms:
            forms.append("paper")
        if domain == "github.com" and "project-release" not in forms:
            forms.append("project-release")
    if not forms:
        forms.append(
            "long-message"
            if len(_clean(item.get("content")))
            >= int(config.TWITTER_LONG_MESSAGE_CHARS)
            else "short-message"
        )
    return forms


def _embedding_tag_ids(item: Dict) -> List[str]:
    topic_tags = {
        str(topic.get("id", "") or ""): str(
            topic.get("tag_id", "") or ""
        )
        for topic in config.TWITTER_INTEREST_TOPICS
        if isinstance(topic, dict)
    }
    stages = item.get("filter_metadata", {}).get("stages", [])
    for stage in reversed(stages):
        if not isinstance(stage, dict) or stage.get("stage") != "embedding":
            continue
        matched = stage.get("matched_topics", [])
        return [
            topic_tags.get(str(topic_id), "")
            for topic_id in matched
            if topic_tags.get(str(topic_id))
        ] if isinstance(matched, list) else []
    return []


def _tag(
    definition: Dict[str, object],
    source: str,
) -> Dict[str, object]:
    return {
        **definition,
        "source": source,
    }


def _build_tags(
    item: Dict,
    taxonomy: Dict[str, Dict[str, object]],
    model_tag_ids: Sequence[str],
    entities: Sequence[str],
    source_text: str,
) -> Tuple[List[Dict[str, object]], List[str]]:
    form_ids = _content_form_ids(item)
    embedding_ids = _embedding_tag_ids(item)
    selected: List[str] = []
    sources: Dict[str, str] = {}
    for tag_id in form_ids + embedding_ids:
        if tag_id in taxonomy and tag_id not in selected:
            selected.append(tag_id)
            sources[tag_id] = (
                "content_rule" if tag_id in form_ids else "embedding"
            )
    for tag_id in model_tag_ids:
        if tag_id in taxonomy and tag_id not in selected:
            selected.append(tag_id)
            sources[tag_id] = "model"
    for tag_id in list(selected):
        parent_id = taxonomy[tag_id]["parent_id"]
        if parent_id and parent_id not in selected:
            selected.append(str(parent_id))
            sources[str(parent_id)] = "taxonomy"

    tags = [
        _tag(definition, sources.get(tag_id, "taxonomy"))
        for tag_id, definition in taxonomy.items()
        if tag_id in selected
    ]
    topic_parent = next(
        (
            tag_id
            for tag_id in selected
            if taxonomy[tag_id]["level"] == 2
            and taxonomy[tag_id]["parent_id"] == "ai"
        ),
        "ai",
    )
    accepted: List[str] = []
    source_casefold = source_text.casefold()
    for entity in entities:
        label = _clean(entity)
        if (
            not label
            or label.casefold() not in source_casefold
            or label.casefold()
            in {value.casefold() for value in accepted}
        ):
            continue
        accepted.append(label)
        if "ai" in taxonomy and not any(tag["id"] == "ai" for tag in tags):
            tags.insert(0, _tag(taxonomy["ai"], "taxonomy"))
        digest = hashlib.sha1(
            label.casefold().encode("utf-8")
        ).hexdigest()[:12]
        tags.append(
            {
                "id": f"entity-{digest}",
                "label": label,
                "level": 3,
                "parent_id": topic_parent,
                "source": "model_entity",
            }
        )
        if len(accepted) >= int(config.TWITTER_ENTITY_LIMIT):
            break
    return tags, accepted


def _first_sentence(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    sentence = re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+", text)[0]
    return sentence[: int(config.TWITTER_ABSTRACT_MAX_CHARS)].strip()


def _two_sentences(value: object) -> str:
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
        : int(config.TWITTER_ABSTRACT_MAX_CHARS)
    ].strip()


def _fallback(item: Dict, taxonomy: Dict[str, Dict[str, object]], error: str) -> Dict:
    source_text = _source_text(item)
    tags, entities = _build_tags(item, taxonomy, [], [], source_text)
    item["title"] = _clean(item.get("content"))[
        : int(config.TWITTER_TITLE_MAX_CHARS)
    ].rstrip("，,。.!！？?") or "X 帖子"
    item["abstract"] = _first_sentence(item.get("content"))
    item["tags"] = tags
    item["entities"] = entities
    item["enrichment_metadata"] = {
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


def _prompt(
    item: Dict,
    taxonomy: Dict[str, Dict[str, object]],
) -> str:
    allowed = [
        {"id": tag["id"], "label": tag["label"]}
        for tag in taxonomy.values()
        if tag["parent_id"] == "ai"
    ]
    return f"""请把下面的 Twitter 内容整理为极简结构化信息。

要求：
1. title 是不超过 {config.TWITTER_TITLE_MAX_CHARS} 个字符的事实性标题。
2. abstract 只用一到两句话说明主要内容，不评价、不扩写。
3. tag_ids 只能从允许的技术标签 ID 中选择。
4. entities 只列出原文或链接文字中明确出现的项目、论文、模型或产品名。
5. 只返回 JSON。

允许的技术标签：
{json.dumps(allowed, ensure_ascii=False)}

返回结构：
{{
  "title": "极简标题",
  "abstract": "一到两句话摘要",
  "tag_ids": ["标签 ID"],
  "entities": ["原文中出现的实体"]
}}

原始内容：
{_source_text(item)}"""


def enrich_twitter_items(
    items: Iterable[Dict],
    client: Optional[object] = None,
) -> List[Dict]:
    """只处理 Twitter 三层筛选后的保留项。"""
    candidates = list(items)
    if not candidates:
        return []
    validate_twitter_enrichment_config()
    taxonomy = _taxonomy()
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

    for item in candidates:
        source_text = _source_text(item)
        if not source_text:
            _fallback(item, taxonomy, "EmptyContent")
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
                    {"role": "user", "content": _prompt(item, taxonomy)},
                ],
                temperature=float(config.TWITTER_ENRICHMENT_TEMPERATURE),
                max_tokens=int(config.TWITTER_ENRICHMENT_MAX_TOKENS),
            )
            parsed = _response_json(response)
            raw_tag_ids = parsed.get("tag_ids", [])
            raw_entities = parsed.get("entities", [])
            model_tag_ids = (
                [str(value) for value in raw_tag_ids]
                if isinstance(raw_tag_ids, list)
                else []
            )
            entities = (
                [str(value) for value in raw_entities]
                if isinstance(raw_entities, list)
                else []
            )
            tags, accepted = _build_tags(
                item,
                taxonomy,
                model_tag_ids,
                entities,
                source_text,
            )
            generated_title = _clean(parsed.get("title"))
            item["title"] = (
                generated_title[: int(config.TWITTER_TITLE_MAX_CHARS)]
                or _clean(item.get("content"))[
                    : int(config.TWITTER_TITLE_MAX_CHARS)
                ]
                or "X 帖子"
            )
            item["abstract"] = (
                _two_sentences(parsed.get("abstract"))
                or _first_sentence(item.get("content"))
            )
            item["tags"] = tags
            item["entities"] = accepted
            item["enrichment_metadata"] = {
                "status": "generated",
                "error_type": "",
            }
        except Exception as exc:
            _fallback(item, taxonomy, type(exc).__name__)
    return candidates
