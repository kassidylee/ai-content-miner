"""确定性生成每个平台的聚合信息流 HTML。"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

import config
from utils.result_store import load_feed_items, validate_platform_key


PLATFORM_LABELS = {
    "x": "X / Twitter",
    "xhs": "小红书",
    "zhihu": "知乎",
}


class FeedRenderError(RuntimeError):
    """信息流页面无法安全生成。"""


def _safe_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return html.escape(url, quote=True)


def _text(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _format_time(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "时间未知"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def _metric(metrics: Dict, name: str) -> int:
    try:
        return max(0, int(metrics.get(name, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _render_tags(tags: object) -> str:
    if not isinstance(tags, list):
        return ""
    rendered: List[str] = []
    for tag in tags:
        if isinstance(tag, dict):
            label = _text(tag.get("label"))
            level = tag.get("level")
        else:
            label = _text(tag)
            level = 0
        if not label:
            continue
        css_level = level if level in {1, 2, 3} else 0
        rendered.append(
            f'<span class="tag tag-level-{css_level}">{label}</span>'
        )
    return "".join(rendered)


def _render_reference_links(referenced_urls: object) -> str:
    if not isinstance(referenced_urls, list):
        return ""
    links: List[str] = []
    seen = set()
    for entry in referenced_urls:
        if not isinstance(entry, dict):
            continue
        url = _safe_url(entry.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        label = _text(entry.get("label") or entry.get("domain") or "相关链接")
        links.append(
            f'<a href="{url}" target="_blank" '
            f'rel="noopener noreferrer">{label}</a>'
        )
    if not links:
        return ""
    return f'<div class="references">{"".join(links)}</div>'


def _debug_details(item: Dict) -> str:
    if not getattr(config, "FEED_DEBUG_METADATA", False):
        return ""
    stages = item.get("filter_metadata", {}).get("stages", [])
    if not isinstance(stages, list):
        return ""
    facts: List[str] = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        if stage.get("stage") == "embedding":
            facts.append(
                "最高相似主题："
                f"{_text(stage.get('best_topic_label') or stage.get('best_topic'))} "
                f"({_text(stage.get('best_score'))})"
            )
        if stage.get("stage") == "comments":
            details = stage.get("details", {})
            if isinstance(details, dict):
                facts.append(
                    f"回复样本：{_text(details.get('sample_size', 0))}，"
                    "加权质疑比例："
                    f"{_text(details.get('weighted_critical_ratio', 0))}"
                )
    reason_codes = item.get("filter_metadata", {}).get(
        "final_reason_codes", []
    )
    if isinstance(reason_codes, list):
        facts.append(f"最终原因：{_text(', '.join(map(str, reason_codes)))}")
    if not facts:
        return ""
    return (
        '<details class="debug"><summary>筛选信息</summary>'
        f"<p>{'<br>'.join(facts)}</p></details>"
    )


def _render_card(item: Dict) -> str:
    title = _text(item.get("title") or "无标题")
    abstract = _text(item.get("abstract") or item.get("content") or "")
    author = _text(item.get("author") or item.get("username") or "未知作者")
    published_at = _text(_format_time(item.get("published_at")))
    source_url = _safe_url(item.get("source_url"))
    tags = _render_tags(item.get("tags"))
    references = _render_reference_links(item.get("referenced_urls"))
    metrics = item.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}

    primary_link = (
        f'<a class="primary-link" href="{source_url}" target="_blank" '
        'rel="noopener noreferrer">查看原帖</a>'
        if source_url
        else '<span class="primary-link disabled">原帖链接不可用</span>'
    )
    return f"""
<article class="card">
  <div class="card-topline">
    <span>{author}</span>
    <time>{published_at}</time>
  </div>
  <h2>{title}</h2>
  <p class="abstract">{abstract}</p>
  <div class="tags">{tags}</div>
  <div class="metrics" aria-label="互动数据">
    <span>点赞 {_metric(metrics, "like_count")}</span>
    <span>回复 {_metric(metrics, "reply_count")}</span>
    <span>转发 {_metric(metrics, "share_count")}</span>
    <span>浏览 {_metric(metrics, "view_count")}</span>
  </div>
  {references}
  <div class="card-actions">{primary_link}</div>
  {_debug_details(item)}
</article>"""


def _document(platform: str, items: Iterable[Dict]) -> str:
    platform_label = _text(PLATFORM_LABELS.get(platform, platform.upper()))
    cards = "\n".join(_render_card(item) for item in items)
    if not cards:
        cards = (
            '<section class="empty">'
            "<h2>暂无符合条件的内容</h2>"
            "<p>页面会在后续采集到保留内容时自动更新。</p>"
            "</section>"
        )
    generated_at = _text(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{platform_label} 信息流</title>
  <style>
    :root {{
      color-scheme: light;
      --background: #f4f6f8;
      --surface: #ffffff;
      --text: #18212b;
      --muted: #687381;
      --line: #dfe4ea;
      --accent: #155eef;
      --accent-soft: #edf3ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--background);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
        "Noto Sans SC", sans-serif;
      line-height: 1.6;
    }}
    main {{ width: min(920px, calc(100% - 32px)); margin: 48px auto 72px; }}
    header {{ margin-bottom: 28px; }}
    h1 {{ margin: 0 0 6px; font-size: clamp(28px, 5vw, 42px); }}
    .subtitle, .card-topline, .metrics {{ color: var(--muted); }}
    .feed {{ display: grid; gap: 18px; }}
    .card, .empty {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 24px;
      box-shadow: 0 4px 18px rgb(24 33 43 / 5%);
    }}
    .card-topline {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      font-size: 14px;
    }}
    h2 {{ margin: 12px 0 8px; font-size: 22px; line-height: 1.35; }}
    .abstract {{ margin: 0 0 16px; }}
    .tags, .metrics, .references {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}
    .tag {{
      border-radius: 999px;
      padding: 3px 10px;
      background: #f0f2f5;
      color: #4c5867;
      font-size: 13px;
    }}
    .tag-level-1 {{ background: #e8edf4; font-weight: 600; }}
    .tag-level-2 {{ background: var(--accent-soft); color: #194da8; }}
    .tag-level-3 {{ border: 1px solid #c8d7f2; background: #fff; }}
    .metrics {{ gap: 18px; font-size: 14px; }}
    .references a {{ color: #3c5d8f; font-size: 14px; }}
    .card-actions {{ margin-top: 20px; }}
    .primary-link {{
      display: inline-block;
      border-radius: 8px;
      padding: 9px 15px;
      background: var(--accent);
      color: #fff;
      text-decoration: none;
      font-weight: 600;
    }}
    .primary-link.disabled {{ background: #8b95a1; }}
    .debug {{ margin-top: 16px; color: var(--muted); font-size: 13px; }}
    @media (max-width: 600px) {{
      main {{ width: min(100% - 20px, 920px); margin-top: 24px; }}
      .card, .empty {{ padding: 18px; }}
      .card-topline {{ display: block; }}
      .card-topline time {{ display: block; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{platform_label} 信息流</h1>
      <div class="subtitle">结构化摘要直接链接原始内容 · 更新于 {generated_at}</div>
    </header>
    <section class="feed">{cards}</section>
  </main>
</body>
</html>
"""


def render_platform_feed(
    platform: object,
    items: Optional[List[Dict]] = None,
    report_dir: Optional[Path] = None,
    processed_dir: Optional[Path] = None,
) -> Path:
    """从结构化事实源生成固定平台页面并原子替换。"""
    platform_key = validate_platform_key(platform)
    feed_items = (
        items
        if items is not None
        else load_feed_items(platform_key, directory=processed_dir)
    )
    destination_dir = Path(report_dir or config.REPORT_DIR)
    destination = destination_dir / f"{platform_key}.html"
    temporary = destination_dir / (
        f".{platform_key}.{uuid4().hex}.html.tmp"
    )
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            _document(platform_key, feed_items),
            encoding="utf-8",
        )
        temporary.replace(destination)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise FeedRenderError(f"信息流页面写入失败：{exc}") from exc
    return destination
