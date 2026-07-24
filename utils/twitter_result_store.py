"""保存 Twitter 结构化结果，并为聚合页读取保留项。"""

from __future__ import annotations

import copy
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from uuid import uuid4

import config


class TwitterResultStoreError(RuntimeError):
    """Twitter 结构化结果无法安全读写。"""


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"无法序列化类型 {type(value).__name__}")


def append_twitter_results(items: Iterable[Dict]) -> Path:
    """原子追加本次唯一候选推文。"""
    destination = Path(config.TWITTER_PROCESSED_FILE)
    unique: Dict[str, Dict] = {}
    for item in items:
        item_id = str(item.get("id", "") or "").strip()
        if not item_id or item.get("platform") != "x":
            raise TwitterResultStoreError(
                "Twitter 结构化结果缺少有效统一 ID 或平台字段"
            )
        record = copy.deepcopy(item)
        record.pop("raw", None)
        unique[item_id] = record

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
        raise TwitterResultStoreError(
            f"Twitter 结构化结果写入失败：{exc}"
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


def load_twitter_feed_items(
    now: Optional[datetime] = None,
) -> List[Dict]:
    """读取最新保留记录，按推文 ID 去重和发布时间倒序。"""
    source = Path(config.TWITTER_PROCESSED_FILE)
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
                    raise TwitterResultStoreError(
                        f"{source} 第 {line_number} 行不是合法 JSON"
                    ) from exc
                if not isinstance(item, dict) or not item.get("id"):
                    raise TwitterResultStoreError(
                        f"{source} 第 {line_number} 行缺少统一 ID"
                    )
                latest[str(item["id"])] = item
    except OSError as exc:
        raise TwitterResultStoreError(
            f"Twitter 结构化结果读取失败：{exc}"
        ) from exc

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current.astimezone(timezone.utc) - timedelta(
        days=int(config.TWITTER_FEED_RETENTION_DAYS)
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
        key=lambda item: float(item.get("_published_sort_time", 0)),
        reverse=True,
    )
    for item in selected:
        item.pop("_published_sort_time", None)
    return selected[: int(config.TWITTER_FEED_MAX_ITEMS)]
