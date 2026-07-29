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
        if level == 1:
            continue
        css_level = level if level in {1, 2, 3} else 0
        rendered.append(
            f'<span class="tag level-{css_level}">'
            f'{_text(tag.get("label"))}</span>'
        )
        if len(rendered) >= 2:
            break
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
    if not links:
        return ""
    return (
        '<details class="source-details"><summary>相关链接</summary>'
        f'<div class="references">{"".join(links)}</div></details>'
    )


def _card(item: Dict) -> str:
    metrics = item.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}
    source_url = _url(item.get("source_url"))
    title = _text(item.get("title") or "无标题")
    linked_title = (
        f'<a href="{source_url}" target="_blank" '
        f'rel="noopener noreferrer">{title}</a>'
        if source_url
        else title
    )
    publication = item.get("publication_metadata", {})
    related_count = 0
    if isinstance(publication, dict):
        related = publication.get("related_source_ids", [])
        related_count = len(related) if isinstance(related, list) else 0
    related_text = (
        f"<span>相关来源 {related_count}</span>"
        if related_count
        else ""
    )
    return f"""
<article class="card">
  <div class="meta">
    <span>{_text(item.get("author") or item.get("username") or "未知作者")}</span>
    <time>{_text(_time(item.get("published_at")))}</time>
  </div>
  <h2>{linked_title}</h2>
  <p class="abstract">{_text(item.get("abstract") or "暂无摘要")}</p>
  <div class="tags">{_tags(item.get("tags"))}</div>
  <div class="metrics">
    <span>点赞 {_metric(metrics, "like_count")}</span>
    <span>回复 {_metric(metrics, "reply_count")}</span>
    <span>转发 {_metric(metrics, "share_count")}</span>
    <span>浏览 {_metric(metrics, "view_count")}</span>
    {related_text}
  </div>
  {_references(item.get("referenced_urls"))}
</article>"""


def _document(
    items: List[Dict],
    digest_date: str,
) -> str:
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
      sans-serif; line-height:1.5; }}
    main {{ width:min(760px,calc(100% - 24px)); margin:32px auto 56px; }}
    h1 {{ margin:0 0 4px; font-size:28px; }}
    .subtitle,.meta,.metrics {{ color:var(--muted); }}
    .feed {{ display:grid; gap:10px; margin-top:20px; }}
    .card,.empty {{ background:var(--surface); border:1px solid var(--line);
      border-radius:12px; padding:16px; }}
    .meta {{ display:flex; justify-content:space-between; gap:16px;
      font-size:13px; }}
    h2 {{ margin:7px 0 5px; font-size:18px; line-height:1.35; }}
    h2 a {{ color:var(--text); text-decoration:none; }}
    h2 a:hover {{ color:var(--accent); }}
    .abstract {{ margin:0; color:#344054; display:-webkit-box;
      -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
    .tags,.metrics,.references {{ display:flex; flex-wrap:wrap; gap:8px;
      margin-top:9px; }}
    .tag {{ border-radius:999px; padding:2px 8px; background:#f0f2f5;
      font-size:12px; }}
    .level-2 {{ background:#edf3ff; color:#194da8; }}
    .level-3 {{ background:#fff; border:1px solid #c8d7f2; }}
    .metrics {{ gap:12px; font-size:12px; }}
    .source-details {{ margin-top:8px; color:var(--muted); font-size:13px; }}
    .source-details summary {{ cursor:pointer; }}
    .references a {{ color:var(--accent); }}
    @media (max-width:560px) {{
      main {{ width:min(100% - 16px,760px); margin-top:20px; }}
      .card,.empty {{ padding:13px; }}
      h1 {{ font-size:24px; }}
      h2 {{ font-size:17px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Twitter 每日精选</h1>
      <div class="subtitle">{_text(digest_date)} · 精选 {len(items)} 条</div>
    </header>
    <section class="feed">{cards}</section>
  </main>
</body>
</html>
"""


def render_twitter_feed(
    items: Optional[List[Dict]] = None,
    *,
    digest_date: Optional[str] = None,
) -> Path:
    """生成与企业微信共享同一列表的每日精选页面。"""
    daily_limit = int(config.TWITTER_DAILY_LIMIT)
    if items is None:
        # 兼容独立重建页面的调用方式：结果存储可能返回多日保留记录，
        # 页面只读取配置允许的前 N 条。工作流显式传入当日选择时仍严格
        # 校验数量，防止上游选择器与展示层对每日上限产生不同理解。
        feed_items = list(load_twitter_feed_items()[:daily_limit])
    else:
        feed_items = list(items)
    if len(feed_items) > daily_limit:
        raise TwitterFeedRenderError("Twitter 精选内容超过每日上限")
    item_ids = [
        str(item.get("id", "") or "")
        for item in feed_items
        if str(item.get("id", "") or "")
    ]
    if len(item_ids) != len(set(item_ids)):
        raise TwitterFeedRenderError("Twitter 精选内容存在重复")
    report_date = digest_date or datetime.now().date().isoformat()
    destination = Path(config.TWITTER_REPORT_FILE)
    temporary = destination.with_name(
        f".{destination.name}.{uuid4().hex}.tmp"
    )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            _document(feed_items, report_date),
            encoding="utf-8",
        )
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
