"""保存 Reddit 结构化结果，并为聚合页读取保留项。"""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from uuid import uuid4

import config
from analyzer.reddit_common import reddit_filter_stage


class RedditResultStoreError(RuntimeError):
    """Reddit 结构化结果无法安全读写。"""


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"无法序列化类型 {type(value).__name__}")


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _post_id(item: Dict) -> str:
    raw = item.get("raw", {})
    raw = raw if isinstance(raw, dict) else {}
    value = str(raw.get("id") or "").strip()
    if value:
        return value.removeprefix("reddit:")
    match = re.search(
        r"/comments/([^/]+)/",
        str(item.get("url", "") or ""),
    )
    return match.group(1) if match else ""


def _score(item: Dict) -> float:
    quality = reddit_filter_stage(item, "quality")
    try:
        return float(quality.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _topic_label(item: Dict) -> str:
    embedding = reddit_filter_stage(item, "embedding")
    return _clean(embedding.get("best_topic_label"))


def build_reddit_result(
    item: Dict,
    processed_at: Optional[datetime] = None,
) -> Dict:
    """将解析后的 Reddit 文章转换为稳定的社交信息流记录。"""
    raw = item.get("raw", {})
    raw = raw if isinstance(raw, dict) else {}
    post_id = _post_id(item)
    if not post_id:
        raise RedditResultStoreError("Reddit 结构化结果缺少帖子 ID")
    metadata = item.get("reddit_filter_metadata", {})
    if not isinstance(metadata, dict):
        raise RedditResultStoreError("Reddit 结构化结果缺少筛选审计")
    original_title = _clean(item.get("title")) or "Reddit 帖子"
    abstract = _clean(item.get("abstract"))
    if not abstract:
        abstract = _clean(item.get("content"))[
            : int(config.REDDIT_ABSTRACT_MAX_CHARS)
        ]
    return {
        "id": f"reddit:{post_id}",
        "platform_item_id": post_id,
        "platform": "reddit",
        "title": (
            _clean(item.get("feed_title"))
            or original_title[: int(config.REDDIT_TITLE_MAX_CHARS)]
        ),
        "original_title": original_title,
        "content": str(item.get("content", "") or ""),
        "abstract": abstract[: int(config.REDDIT_ABSTRACT_MAX_CHARS)],
        "source_url": str(item.get("url", "") or "").strip(),
        "external_url": str(raw.get("external_url", "") or "").strip(),
        "published_at": item.get("publish_time"),
        "author": _clean(item.get("author")),
        "subreddit": _clean(
            raw.get("subreddit") or raw.get("search_subreddit")
        ),
        "score": round(_score(item), 2),
        "topic_label": _topic_label(item),
        "filter_metadata": copy.deepcopy(metadata),
        "enrichment_metadata": copy.deepcopy(
            item.get("reddit_enrichment_metadata", {})
        ),
        "processed_at": processed_at or datetime.now(timezone.utc),
    }


def append_reddit_results(items: Iterable[Dict]) -> Path:
    """原子追加本次唯一 Reddit 记录。"""
    destination = Path(config.REDDIT_PROCESSED_FILE)
    unique: Dict[str, Dict] = {}
    for item in items:
        item_id = str(item.get("id", "") or "").strip()
        if not item_id or item.get("platform") != "reddit":
            raise RedditResultStoreError(
                "Reddit 结构化结果缺少有效统一 ID 或平台字段"
            )
        unique[item_id] = copy.deepcopy(item)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid4().hex}.tmp"
    )
    try:
        with temporary.open("wb") as output:
            if destination.exists():
                existing = destination.read_bytes()
                output.write(existing)
                if existing and not existing.endswith(b"\n"):
                    output.write(b"\n")
            for record in unique.values():
                output.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=_json_default,
                    ).encode("utf-8")
                    + b"\n"
                )
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    except (OSError, TypeError, ValueError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise RedditResultStoreError(
            f"Reddit 结构化结果写入失败：{exc}"
        ) from exc
    return destination


def _datetime(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(
                value.strip().replace("Z", "+00:00")
            )
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_reddit_feed_items(
    now: Optional[datetime] = None,
) -> List[Dict]:
    """读取最新保留记录，按帖子 ID 去重和质量分排序。"""
    source = Path(config.REDDIT_PROCESSED_FILE)
    if not source.exists():
        return []
    latest: Dict[str, Dict] = {}
    try:
        with source.open("r", encoding="utf-8") as input_file:
            for line_number, line in enumerate(input_file, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RedditResultStoreError(
                        f"{source} 第 {line_number} 行不是合法 JSON"
                    ) from exc
                if not isinstance(item, dict) or not item.get("id"):
                    raise RedditResultStoreError(
                        f"{source} 第 {line_number} 行缺少统一 ID"
                    )
                latest[str(item["id"])] = item
    except OSError as exc:
        raise RedditResultStoreError(
            f"Reddit 结构化结果读取失败：{exc}"
        ) from exc

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current.astimezone(timezone.utc) - timedelta(
        days=int(config.REDDIT_FEED_RETENTION_DAYS)
    )
    selected: List[Dict] = []
    for item in latest.values():
        metadata = item.get("filter_metadata", {})
        published_at = _datetime(item.get("published_at"))
        if (
            not isinstance(metadata, dict)
            or metadata.get("final_decision") != "keep"
            or published_at is None
            or published_at < cutoff
        ):
            continue
        item["_published_sort_time"] = published_at.timestamp()
        selected.append(item)
    selected.sort(
        key=lambda item: (
            float(item.get("score", 0.0) or 0.0),
            float(item.get("_published_sort_time", 0.0)),
        ),
        reverse=True,
    )
    for item in selected:
        item.pop("_published_sort_time", None)
    return selected[: int(config.REDDIT_FEED_MAX_ITEMS)]
