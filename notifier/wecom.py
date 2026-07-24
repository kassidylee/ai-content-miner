"""可选的企业微信结构化信息流通知。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

import config


MAX_MESSAGE_BYTES = 4096


def _is_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _escape_markdown(value: object) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return re.sub(r"([\\`*_[\]()#+.!-])", r"\\\1", text)


def validate_config() -> bool:
    """只在通知启用后检查 Webhook。"""
    webhook = str(getattr(config, "WECOM_WEBHOOK", "") or "").strip()
    placeholders = ("your-webhook-key", "your-key", "example.com")
    return _is_http_url(webhook) and not any(
        placeholder in webhook.casefold() for placeholder in placeholders
    )


def send_markdown_v2(content: str) -> bool:
    payload = {"msgtype": "markdown_v2", "markdown_v2": {"content": content}}
    try:
        response = requests.post(
            config.WECOM_WEBHOOK,
            json=payload,
            timeout=10,
        )
        if response.status_code != 200:
            return False
        data = response.json()
        return isinstance(data, dict) and data.get("errcode") == 0
    except (requests.RequestException, ValueError):
        return False


def _item_lines(index: int, item: Dict) -> List[str]:
    title = _escape_markdown(item.get("title") or "无标题")
    abstract = _escape_markdown(item.get("abstract") or "")
    platform = _escape_markdown(item.get("platform") or "unknown")
    source_url = str(item.get("source_url", "") or "").strip()
    lines = [
        f"**{index}. {title}**",
        f"- 平台：{platform}",
    ]
    if abstract:
        lines.append(f"- 摘要：{abstract}")
    if _is_http_url(source_url):
        lines.append(f"- [查看原帖]({source_url})")
    lines.append("")
    return lines


def build_markdown(items: List[Dict], platform: Optional[str] = None) -> str:
    """在字节上限内构造直接链接原帖的消息。"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# AI 信息流 - {today}",
        "",
        f"- 本次保留：{len(items)} 条",
        "",
    ]

    for index, item in enumerate(items[:10], start=1):
        candidate = lines + _item_lines(index, item)
        if len("\n".join(candidate).encode("utf-8")) > MAX_MESSAGE_BYTES:
            break
        lines = candidate

    base_url = str(getattr(config, "REPORT_BASE_URL", "") or "").rstrip("/")
    if platform and _is_http_url(base_url):
        aggregate = f"{base_url}/{platform}.html"
        candidate = lines + [f"[查看 {platform} 聚合页]({aggregate})"]
        if len("\n".join(candidate).encode("utf-8")) <= MAX_MESSAGE_BYTES:
            lines = candidate
    return "\n".join(lines)


def send_to_wecom(items: List[Dict], platform: Optional[str] = None) -> bool:
    """发送可选通知；调用方负责决定失败是否影响退出状态。"""
    if not validate_config():
        return False
    return send_markdown_v2(build_markdown(items, platform=platform))
