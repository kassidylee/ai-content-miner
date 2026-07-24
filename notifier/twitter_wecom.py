"""Twitter 新流程的可选企业微信通知。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List
from urllib.parse import urlparse

import config


def _http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _markdown(value: object) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return re.sub(r"([\\`*_[\]()#+.!-])", r"\\\1", text)


def validate_twitter_wecom_config() -> List[str]:
    if not config.TWITTER_ENABLE_WECOM:
        return []
    webhook = str(config.WECOM_WEBHOOK or "").strip()
    placeholders = ("your-webhook-key", "your-key", "example.com")
    if not _http_url(webhook) or any(
        value in webhook.casefold() for value in placeholders
    ):
        return ["启用 Twitter 企业微信通知时必须配置有效 WECOM_WEBHOOK"]
    return []


def send_twitter_wecom(items: List[Dict]) -> bool:
    """发送直接链接原帖的 Twitter 摘要。"""
    if validate_twitter_wecom_config():
        return False
    import requests

    lines = [
        f"# Twitter 信息流 - {datetime.now():%Y-%m-%d}",
        "",
        f"- 本次保留：{len(items)} 条",
        "",
    ]
    for index, item in enumerate(items[:10], start=1):
        source_url = str(item.get("source_url", "") or "").strip()
        lines.extend(
            [
                f"**{index}. {_markdown(item.get('title') or '无标题')}**",
                f"- 摘要：{_markdown(item.get('abstract') or '')}",
            ]
        )
        if _http_url(source_url):
            safe_url = source_url.replace("(", "%28").replace(")", "%29")
            lines.append(f"- [查看原帖]({safe_url})")
        lines.append("")

    content = "\n".join(lines)
    if len(content.encode("utf-8")) > 4096:
        content = "\n".join(lines[:4] + ["消息过长，请查看聚合页面。"])
    try:
        response = requests.post(
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
