"""按平台保存结构化结果，并为信息流读取保留项。"""

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


PLATFORM_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class ResultStoreError(RuntimeError):
    """结构化结果无法安全读写。"""


def validate_platform_key(platform: object) -> str:
    """限制平台键，避免使用内容或路径片段拼接文件名。"""
    value = str(platform or "").strip().lower()
    if not PLATFORM_PATTERN.fullmatch(value):
        raise ResultStoreError(f"无效的平台键：{value!r}")
    return value


def processed_path(
    platform: object,
    directory: Optional[Path] = None,
) -> Path:
    platform_key = validate_platform_key(platform)
    base_dir = Path(directory or config.PROCESSED_DIR)
    return base_dir / f"{platform_key}.jsonl"


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"无法序列化类型 {type(value).__name__}")


def _storage_record(item: Dict) -> Dict:
    """移除采集器原始响应，只保留下游标准字段。"""
    record = copy.deepcopy(item)
    record.pop("raw", None)
    return record


def append_processed_items(
    platform: object,
    items: Iterable[Dict],
    directory: Optional[Path] = None,
) -> Path:
    """原子追加本次唯一候选项。"""
    platform_key = validate_platform_key(platform)
    destination = processed_path(platform_key, directory)
    unique_items: Dict[str, Dict] = {}
    for item in items:
        item_id = str(item.get("id", "") or "").strip()
        item_platform = validate_platform_key(item.get("platform"))
        if not item_id:
            raise ResultStoreError("结构化结果缺少统一内容 ID")
        if item_platform != platform_key:
            raise ResultStoreError(
                f"内容 {item_id} 的平台 {item_platform} 与输出平台不一致"
            )
        unique_items[item_id] = _storage_record(item)

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
            for item in unique_items.values():
                line = json.dumps(
                    item,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=_json_default,
                )
                output.write(line.encode("utf-8") + b"\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    except (OSError, TypeError, ValueError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ResultStoreError(f"结构化结果写入失败：{exc}") from exc
    return destination


def _parse_datetime(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_feed_items(
    platform: object,
    directory: Optional[Path] = None,
    retention_days: Optional[int] = None,
    max_items: Optional[int] = None,
    now: Optional[datetime] = None,
) -> List[Dict]:
    """读取最终保留项，按统一 ID 去重并按发布时间倒序。"""
    source = processed_path(platform, directory)
    if not source.exists():
        return []

    latest_by_id: Dict[str, Dict] = {}
    try:
        with source.open("r", encoding="utf-8") as input_file:
            for line_number, line in enumerate(input_file, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ResultStoreError(
                        f"{source} 第 {line_number} 行不是合法 JSON"
                    ) from exc
                if not isinstance(item, dict):
                    raise ResultStoreError(
                        f"{source} 第 {line_number} 行不是 JSON 对象"
                    )
                item_id = str(item.get("id", "") or "").strip()
                if not item_id:
                    raise ResultStoreError(
                        f"{source} 第 {line_number} 行缺少统一内容 ID"
                    )
                latest_by_id[item_id] = item
    except OSError as exc:
        raise ResultStoreError(f"结构化结果读取失败：{exc}") from exc

    selected_retention = (
        retention_days
        if retention_days is not None
        else int(getattr(config, "FEED_RETENTION_DAYS", 30))
    )
    selected_limit = (
        max_items
        if max_items is not None
        else int(getattr(config, "FEED_MAX_ITEMS", 200))
    )
    if selected_retention <= 0 or selected_limit <= 0:
        raise ResultStoreError("信息流保留期和最大数量必须大于 0")

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    cutoff = current_time.astimezone(timezone.utc) - timedelta(
        days=selected_retention
    )

    kept: List[Dict] = []
    for item in latest_by_id.values():
        metadata = item.get("filter_metadata", {})
        if not isinstance(metadata, dict):
            continue
        if metadata.get("final_decision") != "keep":
            continue
        published_at = _parse_datetime(item.get("published_at"))
        if published_at is None or published_at < cutoff:
            continue
        item["_published_sort_time"] = published_at.timestamp()
        kept.append(item)

    kept.sort(
        key=lambda item: float(item.get("_published_sort_time", 0)),
        reverse=True,
    )
    for item in kept:
        item.pop("_published_sort_time", None)
    return kept[:selected_limit]
