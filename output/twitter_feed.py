"""确定性生成 Twitter 聚合信息流 HTML。"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

import config
from utils.twitter_result_store import load_twitter_feed_items


class TwitterFeedRenderError(RuntimeError):
    """Twitter 聚合页无法安全生成。"""


def _text(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return html.escape(url, quote=True)


def _time(value: object) -> str:
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text or "时间未知"


def _metric(metrics: Dict, name: str) -> int:
    try:
        return max(0, int(metrics.get(name, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _tags(value: object) -> str:
    if not isinstance(value, list):
        return ""
    rendered: List[str] = []
    for tag in value:
        if not isinstance(tag, dict):
            continue
        level = tag.get("level")
        css_level = level if level in {1, 2, 3} else 0
        rendered.append(
            f'<span class="tag level-{css_level}">'
            f'{_text(tag.get("label"))}</span>'
        )
    return "".join(rendered)


def _references(value: object) -> str:
    if not isinstance(value, list):
        return ""
    links: List[str] = []
    seen = set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        url = _url(entry.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        label = _text(
            entry.get("label") or entry.get("domain") or "相关链接"
        )
        links.append(
            f'<a href="{url}" target="_blank" '
            f'rel="noopener noreferrer">{label}</a>'
        )
    return (
        f'<div class="references">{"".join(links)}</div>'
        if links
        else ""
    )


def _card(item: Dict) -> str:
    metrics = item.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}
    source_url = _url(item.get("source_url"))
    primary = (
        f'<a class="primary" href="{source_url}" target="_blank" '
        'rel="noopener noreferrer">查看原帖</a>'
        if source_url
        else '<span class="primary disabled">原帖链接不可用</span>'
    )
    return f"""
<article class="card">
  <div class="meta">
    <span>{_text(item.get("author") or item.get("username") or "未知作者")}</span>
    <time>{_text(_time(item.get("published_at")))}</time>
  </div>
  <h2>{_text(item.get("title") or "无标题")}</h2>
  <p>{_text(item.get("abstract") or "暂无摘要")}</p>
  <div class="tags">{_tags(item.get("tags"))}</div>
  <div class="metrics">
    <span>点赞 {_metric(metrics, "like_count")}</span>
    <span>回复 {_metric(metrics, "reply_count")}</span>
    <span>转发 {_metric(metrics, "share_count")}</span>
    <span>浏览 {_metric(metrics, "view_count")}</span>
  </div>
  {_references(item.get("referenced_urls"))}
  <div class="actions">{primary}</div>
</article>"""


def _document(items: List[Dict]) -> str:
    cards = "\n".join(_card(item) for item in items)
    if not cards:
        cards = (
            '<section class="empty"><h2>暂无符合条件的内容</h2>'
            "<p>页面会在后续采集到保留内容时自动更新。</p></section>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>X / Twitter 信息流</title>
  <style>
    :root {{ --bg:#f4f6f8; --surface:#fff; --text:#18212b;
      --muted:#687381; --line:#dfe4ea; --accent:#155eef; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text);
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",
      sans-serif; line-height:1.6; }}
    main {{ width:min(920px,calc(100% - 32px)); margin:48px auto 72px; }}
    h1 {{ margin-bottom:6px; }}
    .subtitle,.meta,.metrics {{ color:var(--muted); }}
    .feed {{ display:grid; gap:18px; margin-top:28px; }}
    .card,.empty {{ background:var(--surface); border:1px solid var(--line);
      border-radius:14px; padding:24px; }}
    .meta {{ display:flex; justify-content:space-between; gap:16px;
      font-size:14px; }}
    h2 {{ margin:12px 0 8px; line-height:1.35; }}
    .tags,.metrics,.references {{ display:flex; flex-wrap:wrap; gap:8px;
      margin-top:12px; }}
    .tag {{ border-radius:999px; padding:3px 10px; background:#f0f2f5;
      font-size:13px; }}
    .level-1 {{ font-weight:600; }}
    .level-2 {{ background:#edf3ff; color:#194da8; }}
    .level-3 {{ background:#fff; border:1px solid #c8d7f2; }}
    .metrics {{ gap:18px; font-size:14px; }}
    .actions {{ margin-top:20px; }}
    .primary {{ display:inline-block; border-radius:8px; padding:9px 15px;
      background:var(--accent); color:#fff; text-decoration:none;
      font-weight:600; }}
    .disabled {{ background:#8b95a1; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>X / Twitter 信息流</h1>
      <div class="subtitle">结构化摘要直接链接原始内容</div>
    </header>
    <section class="feed">{cards}</section>
  </main>
</body>
</html>
"""


def render_twitter_feed(items: Optional[List[Dict]] = None) -> Path:
    """从 Twitter 事实源生成固定 x.html 并原子替换。"""
    feed_items = items if items is not None else load_twitter_feed_items()
    destination = Path(config.TWITTER_REPORT_FILE)
    temporary = destination.with_name(
        f".{destination.name}.{uuid4().hex}.tmp"
    )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(_document(feed_items), encoding="utf-8")
        temporary.replace(destination)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise TwitterFeedRenderError(
            f"Twitter 聚合页写入失败：{exc}"
        ) from exc
    return destination
