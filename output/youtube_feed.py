"""Map YTB_LLM digests into YouTube structured-feed records and render them."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

import config
from utils.youtube_result_store import load_youtube_feed_items


class YoutubeFeedError(RuntimeError):
    """YouTube feed records or HTML could not be safely produced."""


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _optional_bool(value: object) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _valid_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _iso_datetime(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise YoutubeFeedError(f"Invalid YouTube published_at value: {text}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _video_filter_metadata(video: Dict, domain: str, digest: Dict) -> Dict:
    details = {
        "digest_date": str(digest.get("date", "") or ""),
        "domain": domain,
        "weights": dict(digest.get("weights", {}))
        if isinstance(digest.get("weights"), dict)
        else {},
    }
    relevance_reason = _clean(video.get("relevance_gate_reason"))
    previous_domain = _clean(video.get("domain_before_relevance_gate"))
    if relevance_reason:
        details["relevance_gate_reason"] = relevance_reason
    if previous_domain:
        details["domain_before_relevance_gate"] = previous_domain
    stages = []
    if relevance_reason or previous_domain:
        stages.append(
            {
                "stage": "ytb_llm_relevance_gate",
                "decision": "pass",
                "reason_codes": ["YOUTUBE_RELEVANCE_GATE_PASSED"],
                "details": {
                    key: value
                    for key, value in {
                        "relevance_gate_reason": relevance_reason,
                        "domain_before_relevance_gate": previous_domain,
                    }.items()
                    if value
                },
            }
        )
    stages.append(
        {
            "stage": "ytb_llm_score_and_select",
            "decision": "pass",
            "score": _float(video.get("final_score")),
            "reason_codes": ["YOUTUBE_DIGEST_PICK_SELECTED"],
            "details": details,
        }
    )
    metadata = {
        "stages": stages,
        "final_decision": "keep",
        "final_reason_codes": ["YOUTUBE_DIGEST_PICK_SELECTED"],
    }
    if relevance_reason:
        metadata["relevance_gate_reason"] = relevance_reason
    if previous_domain:
        metadata["domain_before_relevance_gate"] = previous_domain
    return metadata


def youtube_records_from_digest(
    digest: Dict,
    processed_at: Optional[datetime] = None,
) -> List[Dict]:
    """Convert all YTB_LLM domain picks into structured feed records."""
    if not isinstance(digest, dict):
        raise YoutubeFeedError("YouTube digest must be a JSON object")
    domains = digest.get("domains", {})
    if not isinstance(domains, dict):
        raise YoutubeFeedError("YouTube digest is missing domains object")

    active_processed_at = processed_at or datetime.now(timezone.utc)
    if active_processed_at.tzinfo is None:
        active_processed_at = active_processed_at.replace(tzinfo=timezone.utc)
    records: List[Dict] = []
    for domain, payload in domains.items():
        if not isinstance(payload, dict):
            continue
        picks = payload.get("picks", [])
        if not isinstance(picks, list):
            continue
        for video in picks:
            if not isinstance(video, dict):
                continue
            video_id = _clean(video.get("video_id"))
            if not video_id:
                raise YoutubeFeedError("YouTube digest pick missing video_id")
            description = str(video.get("description", "") or "")
            record = {
                "id": f"youtube:{video_id}",
                "platform_item_id": video_id,
                "platform": "youtube",
                "title": _clean(video.get("title")) or "YouTube video",
                "content": description,
                "abstract": _clean(description)[:300],
                "source_url": str(video.get("url", "") or "").strip(),
                "published_at": _iso_datetime(video.get("published_at")),
                "author": _clean(video.get("channel_name")),
                "metrics": {
                    "view_count": _int(video.get("view_count")),
                    "like_count": _int(video.get("like_count")),
                    "comment_count": _int(video.get("comment_count")),
                },
                "score": _float(video.get("final_score")),
                "topic_label": _clean(video.get("domain")) or _clean(domain),
                "filter_metadata": _video_filter_metadata(video, str(domain), digest),
                "enrichment_metadata": {
                    "authority_score": _float(video.get("authority_score")),
                    "authority_note": str(video.get("authority_note", "") or ""),
                    "score_breakdown": dict(video.get("score_breakdown", {}))
                    if isinstance(video.get("score_breakdown"), dict)
                    else {},
                },
                "platform_metadata": {
                    "channel_id": _clean(video.get("channel_id")),
                    "duration": str(video.get("duration", "") or ""),
                    "duration_seconds": _int(video.get("duration_seconds")),
                    "needs_relevance_check": _optional_bool(
                        video.get("needs_relevance_check")
                    ),
                },
                "processed_at": active_processed_at,
            }
            validate_youtube_record(record)
            records.append(record)
    return records


def validate_youtube_record(record: Dict) -> None:
    """Validate the stable fields expected by YouTube storage/rendering."""
    required = (
        "id",
        "platform_item_id",
        "platform",
        "title",
        "source_url",
        "published_at",
        "author",
        "metrics",
        "score",
        "topic_label",
        "filter_metadata",
        "enrichment_metadata",
        "platform_metadata",
        "processed_at",
    )
    missing = [field for field in required if field not in record]
    if missing:
        raise YoutubeFeedError(f"YouTube record missing fields: {', '.join(missing)}")
    if record["platform"] != "youtube":
        raise YoutubeFeedError("YouTube record platform must be youtube")
    if not str(record["id"]).startswith("youtube:"):
        raise YoutubeFeedError("YouTube record id must start with youtube:")
    if not _valid_http_url(record["source_url"]):
        raise YoutubeFeedError("YouTube record source_url must be http/https")
    _iso_datetime(record["published_at"])
    if not isinstance(record["metrics"], dict):
        raise YoutubeFeedError("YouTube record metrics must be an object")
    metadata = record["filter_metadata"]
    if not isinstance(metadata, dict) or metadata.get("final_decision") != "keep":
        raise YoutubeFeedError("YouTube filter_metadata must mark final_decision=keep")
    if not isinstance(record["enrichment_metadata"], dict):
        raise YoutubeFeedError("YouTube enrichment_metadata must be an object")
    if not isinstance(record["platform_metadata"], dict):
        raise YoutubeFeedError("YouTube platform_metadata must be an object")


def _text(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _url(value: object) -> str:
    url = str(value or "").strip()
    return html.escape(url, quote=True) if _valid_http_url(url) else ""


def _time(value: object) -> str:
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d %H:%M"
        )
    except ValueError:
        return text or "time unknown"


def _metric(metrics: Dict, name: str) -> int:
    return _int(metrics.get(name, 0))


def _card(item: Dict) -> str:
    metrics = item.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}
    source_url = _url(item.get("source_url"))
    title = _text(item.get("title") or "Untitled")
    linked_title = (
        f'<a href="{source_url}" target="_blank" rel="noopener noreferrer">{title}</a>'
        if source_url
        else title
    )
    return f"""
<article class="card">
  <div class="meta">
    <span>{_text(item.get("author") or "Unknown channel")}</span>
    <time>{_text(_time(item.get("published_at")))}</time>
  </div>
  <h2>{linked_title}</h2>
  <p class="abstract">{_text(item.get("abstract") or "No description available.")}</p>
  <div class="signals">
    <span class="score">Score {_text(f"{float(item.get('score', 0) or 0):.2f}")}</span>
    <span class="tag">{_text(item.get("topic_label"))}</span>
  </div>
  <div class="metrics">
    <span>Views {_metric(metrics, "view_count")}</span>
    <span>Likes {_metric(metrics, "like_count")}</span>
    <span>Comments {_metric(metrics, "comment_count")}</span>
  </div>
</article>"""


def _document(items: Iterable[Dict]) -> str:
    cards = "\n".join(_card(item) for item in items)
    if not cards:
        cards = (
            '<section class="empty"><h2>No matching YouTube picks</h2>'
            "<p>The page will update after YouTube digest records are written.</p></section>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>YouTube Technical Feed</title>
  <style>
    :root {{ --bg:#f5f6f8; --surface:#fff; --text:#1f2933;
      --muted:#667085; --line:#e3e7ed; --accent:#c4302b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text);
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; line-height:1.55; }}
    main {{ width:min(900px,calc(100% - 32px)); margin:40px auto 64px; }}
    h1 {{ margin:0 0 4px; font-size:28px; }}
    .subtitle,.meta,.metrics {{ color:var(--muted); }}
    .feed {{ display:grid; gap:12px; margin-top:22px; }}
    .card,.empty {{ background:var(--surface); border:1px solid var(--line);
      border-radius:12px; padding:18px; }}
    .meta {{ display:flex; justify-content:space-between; gap:16px; font-size:13px; }}
    h2 {{ margin:8px 0 6px; font-size:19px; line-height:1.35; }}
    h2 a {{ color:var(--text); text-decoration:none; }}
    h2 a:hover {{ color:var(--accent); }}
    .abstract {{ margin:0; color:#344054; }}
    .signals,.metrics {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:10px; }}
    .score,.tag {{ border-radius:999px; padding:2px 9px; background:#f0f2f5; font-size:12px; }}
    .tag {{ background:#fff0ef; color:#9f1f1a; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>YouTube Technical Feed</h1>
      <div class="subtitle">Structured picks from YTB_LLM</div>
    </header>
    <section class="feed">{cards}</section>
  </main>
</body>
</html>
"""


def render_youtube_feed(items: Optional[List[Dict]] = None) -> Path:
    """Render the YouTube structured feed page."""
    feed_items = items if items is not None else load_youtube_feed_items()
    destination = Path(config.YOUTUBE_REPORT_FILE)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(_document(feed_items), encoding="utf-8")
        temporary.replace(destination)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise YoutubeFeedError(f"YouTube feed page write failed: {exc}") from exc
    return destination
