"""确定性生成 Reddit 聚合信息流 HTML。"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

import config
from utils.reddit_result_store import load_reddit_feed_items


class RedditFeedRenderError(RuntimeError):
    """Reddit 聚合页无法安全生成。"""


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


def _card(item: Dict) -> str:
    source_url = _url(item.get("source_url"))
    external_url = _url(item.get("external_url"))
    primary = (
        f'<a class="primary" href="{source_url}" target="_blank" '
        'rel="noopener noreferrer">查看 Reddit 原帖</a>'
        if source_url
        else '<span class="primary disabled">原帖链接不可用</span>'
    )
    external = (
        f'<a class="secondary" href="{external_url}" target="_blank" '
        'rel="noopener noreferrer">查看外部来源</a>'
        if external_url and external_url != source_url
        else ""
    )
    subreddit = _text(item.get("subreddit") or "未知社区")
    topic = _text(item.get("topic_label"))
    topic_badge = f'<span class="tag">{topic}</span>' if topic else ""
    return f"""
<article class="card">
  <div class="meta">
    <span>r/{subreddit} · {_text(item.get("author") or "未知作者")}</span>
    <time>{_text(_time(item.get("published_at")))}</time>
  </div>
  <h2>{_text(item.get("title") or "无标题")}</h2>
  <p>{_text(item.get("abstract") or "暂无摘要")}</p>
  <div class="signals">
    <span class="score">质量分 {_text(f"{float(item.get('score', 0) or 0):.1f}")}/10</span>
    {topic_badge}
  </div>
  <div class="actions">{primary}{external}</div>
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
  <title>Reddit 技术信息流</title>
  <style>
    :root {{ --bg:#f5f6f8; --surface:#fff; --text:#1f2933;
      --muted:#667085; --line:#e3e7ed; --accent:#ff4500; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text);
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",
      sans-serif; line-height:1.6; }}
    main {{ width:min(920px,calc(100% - 32px)); margin:48px auto 72px; }}
    h1 {{ margin-bottom:6px; }}
    .subtitle,.meta {{ color:var(--muted); }}
    .feed {{ display:grid; gap:18px; margin-top:28px; }}
    .card,.empty {{ background:var(--surface); border:1px solid var(--line);
      border-radius:14px; padding:24px; }}
    .meta {{ display:flex; justify-content:space-between; gap:16px;
      font-size:14px; }}
    h2 {{ margin:12px 0 8px; line-height:1.35; }}
    .signals,.actions {{ display:flex; flex-wrap:wrap; gap:10px;
      margin-top:14px; }}
    .score,.tag {{ border-radius:999px; padding:3px 10px;
      background:#f1f3f5; font-size:13px; }}
    .tag {{ background:#fff1eb; color:#a43100; }}
    .primary,.secondary {{ display:inline-block; border-radius:8px;
      padding:9px 15px; text-decoration:none; font-weight:600; }}
    .primary {{ background:var(--accent); color:#fff; }}
    .secondary {{ background:#eef1f5; color:var(--text); }}
    .disabled {{ background:#8b95a1; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Reddit 技术信息流</h1>
      <div class="subtitle">极简摘要、质量信号与原帖直链</div>
    </header>
    <section class="feed">{cards}</section>
  </main>
</body>
</html>
"""


def render_reddit_feed(items: Optional[List[Dict]] = None) -> Path:
    """从 Reddit 事实源生成固定 reddit.html 并原子替换。"""
    feed_items = items if items is not None else load_reddit_feed_items()
    destination = Path(config.REDDIT_REPORT_FILE)
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
        raise RedditFeedRenderError(
            f"Reddit 聚合页写入失败：{exc}"
        ) from exc
    return destination
