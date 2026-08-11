"""Reddit 社交信息流的可选企业微信通知。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import config


def _http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _plain(value: object) -> str:
    """清理控制字符，不对普通标点添加可见反斜杠。"""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return (
        text.replace("\\", "")
        .replace("*", "")
        .replace("[", "【")
        .replace("]", "】")
        .replace("<", "＜")
        .replace(">", "＞")
    )


def validate_reddit_wecom_config() -> List[str]:
    if not config.REDDIT_ENABLE_WECOM:
        return []
    webhook = str(config.WECOM_WEBHOOK or "").strip()
    placeholders = ("your-webhook-key", "your-key", "example.com")
    if not _http_url(webhook) or any(
        value in webhook.casefold() for value in placeholders
    ):
        return ["启用 Reddit 企业微信通知时必须配置有效 WECOM_WEBHOOK"]
    for name in ("REDDIT_WECOM_MAX_ITEMS", "REDDIT_WECOM_MAX_BYTES"):
        value = getattr(config, name, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return [f"{name} 必须是正整数"]
    return []


def _item_block(item: Dict, index: int) -> str:
    title = _plain(item.get("title") or "无标题")
    abstract = _plain(item.get("abstract") or "暂无摘要")
    subreddit = _plain(item.get("subreddit") or "未知社区")
    try:
        score = float(item.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    lines = [
        f"**{index}. {title}**",
        f"- 评分：{score:.1f}/10｜社区：r/{subreddit}",
        f"- 摘要：{abstract}",
    ]
    source_url = str(item.get("source_url", "") or "").strip()
    if _http_url(source_url):
        safe_url = source_url.replace("(", "%28").replace(")", "%29")
        lines.append(f"- [查看 Reddit 原帖]({safe_url})")
    return "\n".join(lines)


def _render_content(items: List[Dict], selected: List[Dict]) -> str:
    lines = [
        f"# Reddit 技术信息流 - {datetime.now():%Y-%m-%d}",
        "",
        (
            f"本次筛选保留：{len(items)} 条｜"
            f"本次推送：{len(selected)} 条"
        ),
        "",
    ]
    for index, item in enumerate(selected, start=1):
        lines.extend([_item_block(item, index), ""])
    return "\n".join(lines).rstrip()


def build_reddit_wecom_content(
    items: List[Dict],
) -> Tuple[str, int]:
    """按完整帖子边界装入企业微信字节预算。"""
    maximum_items = int(config.REDDIT_WECOM_MAX_ITEMS)
    maximum_bytes = int(config.REDDIT_WECOM_MAX_BYTES)
    selected: List[Dict] = []
    for item in items[:maximum_items]:
        candidate = selected + [item]
        content = _render_content(items, candidate)
        if len(content.encode("utf-8")) > maximum_bytes:
            break
        selected = candidate
    content = _render_content(items, selected)
    if len(content.encode("utf-8")) > maximum_bytes:
        content = (
            f"# Reddit 技术信息流 - {datetime.now():%Y-%m-%d}\n\n"
            f"本次筛选保留：{len(items)} 条"
        )
        selected = []
    return content, len(selected)


def send_reddit_wecom(
    items: List[Dict],
    session: Optional[object] = None,
) -> bool:
    """发送标题、极简摘要和 Reddit 原帖直链。"""
    if validate_reddit_wecom_config():
        return False
    import requests

    content, _ = build_reddit_wecom_content(items)
    active_session = session or requests
    try:
        response = active_session.post(
            config.WECOM_WEBHOOK,
            json={
                "msgtype": "markdown_v2",
                "markdown_v2": {"content": content},
            },
            timeout=10,
        )
        if response.status_code != 200:
            return False
        data = response.json()
        return isinstance(data, dict) and data.get("errcode") == 0
    except (requests.RequestException, ValueError):
        return False
