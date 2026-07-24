"""Twitter 采集结果的专用标准化入口。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

import config


def _count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _published_at(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _referenced_urls(value: object) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: List[Dict[str, str]] = []
    seen = set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url", "") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if url in seen:
            continue
        seen.add(url)
        normalized.append(
            {
                "url": url,
                "label": str(entry.get("label", "") or url).strip(),
                "domain": parsed.netloc.casefold(),
            }
        )
    return normalized


def normalize_twitter_item(raw: Dict) -> Dict:
    """将 twscrape JSONL 转换为 Twitter 新流程的统一结构。"""
    tweet_id = str(raw.get("id", "") or "").strip()
    content = str(raw.get("content", "") or "").strip()
    source_url = str(raw.get("source_url") or raw.get("url") or "").strip()
    metadata = raw.get("platform_metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "id": f"x:{tweet_id}" if tweet_id else "",
        "platform_item_id": tweet_id,
        "platform": "x",
        "title": str(raw.get("title", "") or "X 帖子"),
        "content": content,
        "quoted_content": str(raw.get("quoted_content", "") or ""),
        "abstract": "",
        "tags": [],
        "entities": [],
        "source_url": source_url,
        "referenced_urls": _referenced_urls(raw.get("referenced_urls")),
        "published_at": _published_at(raw.get("publish_time")),
        "author": str(raw.get("author", "") or ""),
        "username": str(raw.get("username", "") or ""),
        "metrics": {
            "like_count": _count(raw.get("like_count")),
            "reply_count": _count(raw.get("comment_count")),
            "share_count": _count(raw.get("share_count")),
            "bookmark_count": _count(raw.get("collect_count")),
            "quote_count": _count(raw.get("quote_count")),
            "view_count": _count(raw.get("view_count")),
        },
        "platform_metadata": {
            **metadata,
            "lang": str(metadata.get("lang") or raw.get("lang") or ""),
            "matched_keywords": list(raw.get("matched_keywords", []))
            if isinstance(raw.get("matched_keywords"), list)
            else (
                [raw["search_keyword"]] if raw.get("search_keyword") else []
            ),
            "has_native_title": False,
        },
        "filter_metadata": {
            "stages": [],
            "final_decision": "pending",
            "final_reason_codes": [],
        },
        "processed_at": None,
    }


def load_twitter_items(data_files: Iterable[Path]) -> List[Dict]:
    """只读取本次 twscrape 运行返回的 JSONL 文件。"""
    items: List[Dict] = []
    for raw_path in data_files:
        path = Path(raw_path)
        if path.suffix != ".jsonl" or "_comments_" in path.name:
            continue
        try:
            with path.open("r", encoding="utf-8") as input_file:
                for line_number, line in enumerate(input_file, start=1):
                    if not line.strip():
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            f"{path.name} 第 {line_number} 行不是合法 JSON"
                        ) from exc
                    if isinstance(raw, dict):
                        items.append(normalize_twitter_item(raw))
        except OSError as exc:
            raise ValueError(f"无法读取 Twitter 数据文件：{path}") from exc

    limit = int(getattr(config, "CRAWL_LIMIT", 0) or 0)
    return items[:limit] if limit > 0 else items
