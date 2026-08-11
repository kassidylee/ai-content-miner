"""企业微信群机器人：紧凑 Markdown 卡片加 COS 在线阅读/下载链接。"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Tuple

import requests

import config


SEND_GAP_SECONDS = 4.0
REPORTS_PER_CARD = 3
MAX_REPORTS_PER_PUSH = 9
MAX_MARKDOWN_BYTES = 4096


def validate_config() -> bool:
    webhook = str(getattr(config, "WECOM_WEBHOOK", "") or "").strip()
    if not webhook:
        print("   ❌ WECOM_WEBHOOK 未配置")
        return False
    if not re.match(
        r"^https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[^&]+$",
        webhook,
    ):
        print("   ❌ WECOM_WEBHOOK 格式无效，请使用群机器人 Webhook")
        return False

    cos_required = {
        "COS_SECRET_ID": getattr(config, "COS_SECRET_ID", ""),
        "COS_SECRET_KEY": getattr(config, "COS_SECRET_KEY", ""),
        "COS_REGION": getattr(config, "COS_REGION", ""),
        "COS_BUCKET": getattr(config, "COS_BUCKET", ""),
    }
    missing = [
        name for name, value in cos_required.items()
        if not str(value or "").strip()
    ]
    if missing:
        print(f"   ❌ COS 配置缺失：{', '.join(missing)}")
        return False
    return True


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """按 UTF-8 字节数截断，避免中文导致 Markdown 超过 4096 字节。"""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _escape_markdown(value: object) -> str:
    """转义用户内容中的企业微信 Markdown 特殊字符。"""
    text = str(value or "")
    specials = r"\\_*[]()~`>#+-=|{}.!"
    result = []

    for char in text:
        if char in specials:
            result.append("\\")
        result.append(char)

    return "".join(result)


def build_compact_card(
    index: int,
    item: Dict,
        summary_limit: int = 180,
) -> str:
    """构建每篇研报对应的紧凑企业微信 Markdown 卡片。"""
    article = item.get("article", {})
    title = str(article.get("title", "无标题")).strip()[:80]
    category = str(item.get("category", "其他")).strip()[:20]
    summary = str(item.get("summary", "未生成摘要")).strip()[:summary_limit]
    total_score = float(item.get("total_score", 0) or 0)
    dimensions = item.get("dimensions", [])
    scores = item.get("scores", [])
    preview_url = str(item.get("_preview_url", "") or "").strip()
    download_url = str(item.get("_download_url", "") or "").strip()

    score_parts = [
        f"{str(name)[:10]} {float(value):.1f}"
        for name, value in zip(dimensions[:3], scores[:3])
    ]
    score_text = " · ".join(score_parts) if score_parts else f"综合 {total_score:.1f}"

    links = " ｜ ".join(
        link for link in (
            f"[在线阅读]({preview_url})" if preview_url else "",
            f"[下载研报]({download_url})" if download_url else "",
        ) if link
    )
    if not links:
        links = "<font color=\"warning\">COS 链接缺失</font>"

    return (
        f"### 📄 {index}. {_escape_markdown(title)}\n"
        f"> 分类：<font color=\"info\">{_escape_markdown(category)}</font>\n"
        f"> 总分：<font color=\"warning\">{total_score:.1f}/10</font>\n\n"
        f"{_escape_markdown(summary)}\n\n"
        f"**评分卡**：{_escape_markdown(score_text)}\n\n"
        f"{links}"
    )


def build_report_batch(start_index: int, items: List[Dict]) -> str:
    """Build one WeCom message while preserving both links per report."""
    for summary_limit in (80, 40, 0):
        cards = [
            build_compact_card(index, item, summary_limit=summary_limit)
            for index, item in enumerate(items, start=start_index)
        ]
        content = "\n\n---\n\n".join(cards)
        if len(content.encode("utf-8")) <= MAX_MARKDOWN_BYTES:
            return content
    raise ValueError("研报链接和基础信息超过企业微信消息大小限制")


def send_markdown(content: str) -> Tuple[bool, Dict]:
    """发送精简 Markdown 卡片。"""
    if len(content.encode("utf-8")) > MAX_MARKDOWN_BYTES:
        return False, {"error": "卡片内容超过企业微信 4096 字节限制"}
    try:
        response = requests.post(
            config.WECOM_WEBHOOK,
            json={
                "msgtype": "markdown",
                                "markdown": {
                    "content": content,
                },
            },
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()

        if data.get("errcode") != 0:
            print(f"   ❌ 卡片发送失败响应：{data}")

        return data.get("errcode") == 0, data

    except requests.RequestException as exc:
        return False, {"error": f"卡片网络请求失败：{exc}"}
    except ValueError as exc:
        return False, {"error": f"卡片响应不是 JSON：{exc}"}
    except Exception as exc:
        return False, {"error": str(exc)}


def send_to_wecom(items: List[Dict]) -> bool:
    """每三篇研报合并为一张企业微信 Markdown 卡片推送。"""
    if not validate_config():
        return False
    if not items:
        print("   ℹ️ 没有入选研报，跳过企业微信推送")
        return True

    ready_items = []
    for index, item in enumerate(items[:MAX_REPORTS_PER_PUSH], start=1):
        if not item.get("_preview_url") or not item.get("_download_url"):
            print(f"   ⚠️ 第 {index} 篇缺少 COS 链接，跳过")
            continue
        ready_items.append(item)

    if not ready_items:
        print("   ❌ 没有成功发送任何研报链接")
        return False

    batch_count = 0
    offset = 0
    while offset < len(ready_items):
        batch = []
        content = ""
        for size in range(
            min(REPORTS_PER_CARD, len(ready_items) - offset),
            0,
            -1,
        ):
            candidate_batch = ready_items[offset : offset + size]
            try:
                candidate_content = build_report_batch(offset + 1, candidate_batch)
            except ValueError:
                continue
            batch = candidate_batch
            content = candidate_content
            break

        if not batch:
            print(
                f"   ❌ 第 {offset + 1} 篇的双链接卡片超过企业微信消息大小限制"
            )
            return False

        ok, detail = send_markdown(content)
        if not ok:
            print(f"   ❌ 第 {batch_count + 1} 组卡片发送失败：{detail}")
            return False

        batch_count += 1
        print(
            f"   ✅ 已推送第 {batch_count} 组，"
            f"包含第 {offset + 1} 至 {offset + len(batch)} 篇研报"
        )
        offset += len(batch)
        if offset < len(ready_items):
            time.sleep(SEND_GAP_SECONDS)

    print(
        f"   ✅ 企业微信推送完成，共 {len(ready_items)} 篇研报、"
        f"{batch_count} 张卡片"
    )
    return True