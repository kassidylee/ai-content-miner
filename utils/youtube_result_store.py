"""Store YouTube structured-feed records produced from YTB_LLM digests."""

from __future__ import annotations

import copy
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from uuid import uuid4

import config


class YoutubeResultStoreError(RuntimeError):
    """YouTube structured results could not be safely read or written."""


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize type {type(value).__name__}")


def append_youtube_results(items: Iterable[Dict]) -> Path:
    """Atomically upsert unique YouTube records for this run by unified ID."""
    destination = Path(config.YOUTUBE_PROCESSED_FILE)
    unique: Dict[str, Dict] = {}
    for item in items:
        item_id = str(item.get("id", "") or "").strip()
        if not item_id or item.get("platform") != "youtube":
            raise YoutubeResultStoreError(
                "YouTube structured result is missing a valid unified ID or platform"
            )
        unique[item_id] = copy.deepcopy(item)

    records: List[Dict] = []
    positions: Dict[str, int] = {}
    if destination.exists():
        try:
            with destination.open("r", encoding="utf-8") as input_file:
                for line_number, line in enumerate(input_file, start=1):
                    if not line.strip():
                        continue
                    try:
                        existing = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise YoutubeResultStoreError(
                            f"{destination} line {line_number} is not valid JSON"
                        ) from exc
                    if not isinstance(existing, dict):
                        raise YoutubeResultStoreError(
                            f"{destination} line {line_number} is not a JSON object"
                        )
                    existing_id = str(existing.get("id", "") or "").strip()
                    if not existing_id:
                        raise YoutubeResultStoreError(
                            f"{destination} line {line_number} is missing unified ID"
                        )
                    if existing_id in positions:
                        records[positions[existing_id]] = existing
                    else:
                        positions[existing_id] = len(records)
                        records.append(existing)
        except OSError as exc:
            raise YoutubeResultStoreError(
                f"YouTube structured result read failed: {exc}"
            ) from exc

    for item_id, record in unique.items():
        if item_id in positions:
            records[positions[item_id]] = record
        else:
            positions[item_id] = len(records)
            records.append(record)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as output:
            for record in records:
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
        raise YoutubeResultStoreError(
            f"YouTube structured result write failed: {exc}"
        ) from exc
    return destination


def _datetime(value: object) -> Optional[datetime]:
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


def load_youtube_feed_items(now: Optional[datetime] = None) -> List[Dict]:
    """Load recent kept YouTube records, deduped by unified ID and score."""
    source = Path(config.YOUTUBE_PROCESSED_FILE)
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
                    raise YoutubeResultStoreError(
                        f"{source} line {line_number} is not valid JSON"
                    ) from exc
                if not isinstance(item, dict) or not item.get("id"):
                    raise YoutubeResultStoreError(
                        f"{source} line {line_number} is missing unified ID"
                    )
                latest[str(item["id"])] = item
    except OSError as exc:
        raise YoutubeResultStoreError(
            f"YouTube structured result read failed: {exc}"
        ) from exc

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current.astimezone(timezone.utc) - timedelta(
        days=int(config.YOUTUBE_FEED_RETENTION_DAYS)
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
    return selected[: int(config.YOUTUBE_FEED_MAX_ITEMS)]
