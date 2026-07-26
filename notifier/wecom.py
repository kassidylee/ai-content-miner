"""Enterprise WeChat Markdown V2 notifications."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Dict, List
from urllib.parse import quote, urlparse

import requests

import config


MARKDOWN_V2_SPECIALS = r"\\_*[]()~`>#+-=|{}.!"


def validate_config() -> bool:
    webhook = str(getattr(config, "WECOM_WEBHOOK", "") or "").strip()
    if not webhook:
        print("   ❌ WECOM_WEBHOOK 未配置")
        return False
    if not _is_http_url(webhook):
        print("   ❌ WECOM_WEBHOOK 不是有效的 http/https 地址")
        return False

    placeholders = (
        "your-webhook-key",
        "your-key",
        "your-api-key-here",
        "sk-xxxxx",
        "example.com",
    )
    if any(value in webhook.lower() for value in placeholders):
        print("   ❌ WECOM_WEBHOOK 仍包含占位值")
        return False

    base_url = str(getattr(config, "REPORT_BASE_URL", "") or "").strip()
    if not _is_http_url(base_url):
        print("   ❌ REPORT_BASE_URL 不是有效的 http/https 地址")
        return False
    if "127.0.0.1" in base_url or "localhost" in base_url:
        print("   ⚠️ REPORT_BASE_URL 是本机地址，企业微信用户无法访问")
    return True


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def escape_markdown_v2(value: object) -> str:
    """Escape ordinary text while preserving official Markdown V2 syntax."""
    text = str(value or "")
    escaped = []
    for char in text:
        if char in MARKDOWN_V2_SPECIALS:
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


def send_markdown_v2(content: str) -> bool:
    payload = {
        "msgtype": "markdown_v2",
        "markdown_v2": {"content": content},
    }
    try:
        response = requests.post(
            config.WECOM_WEBHOOK,
            json=payload,
            timeout=10,
        )
        if response.status_code != 200:
            print(f"   ❌ 企业微信 HTTP 错误: {response.status_code}")
            print(f"   📄 响应内容: {response.text[:500]}")
            return False
        data = response.json()
        if data.get("errcode") == 0:
            return True
        print(
            f"   ❌ 企业微信错误: errcode={data.get('errcode')}, "
            f"errmsg={data.get('errmsg')}"
        )
        print(f"   📄 响应内容: {response.text[:500]}")
        return False
    except requests.exceptions.Timeout:
        print("   ❌ 企业微信连接超时（10s）")
    except requests.exceptions.ConnectionError as exc:
        print(f"   ❌ 企业微信连接失败: {exc}")
    except Exception as exc:
        print(f"   ❌ 企业微信发送异常: {exc}")
    return False


def sanitize_filename(title: str) -> str:
    safe = re.sub(r"[^\w\s\u4e00-\u9fff]", "", title)
    safe = safe.strip()[:40].replace(" ", "_")
    return safe or "未命名"


def get_report_link(item: Dict, base_url: str) -> str:
    preview_url = str(item.get("_preview_url", "") or "").strip()
    if preview_url:
        return preview_url
    output_path = str(item.get("_output_path", "") or "")
    if output_path:
        filename = os.path.basename(output_path)
    else:
        article = item.get("article", {})
        title = str(article.get("title", "无标题"))
        filename = sanitize_filename(title) + ".html"
        print(f"   ⚠️ 未找到输出路径，使用默认链接: {filename}")

    if output_path and not os.path.isfile(output_path):
        print(f"   ⚠️ 报告文件不存在: {output_path}")

    # Encode only the path segment; keep the scheme, host, and base path intact.
    encoded_filename = quote(filename, safe="")
    return f"{base_url.rstrip('/')}/{encoded_filename}"


def _link(label: str, url: str) -> str:
    # The URL must remain unescaped inside the Markdown link target.
    return f"[{escape_markdown_v2(label)}]({url})"


def _build_content(items: List[Dict], base_url: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# {escape_markdown_v2('AI 前沿日报 - ' + today)}",
        "",
        f"<font color=\"info\">处理文章：{len(items)} 篇</font>",
        "",
        "## 深度挖掘队列",
        "",
    ]

    for index, item in enumerate(items[:10], start=1):
        article = item.get("article", {})
        title = str(article.get("title", "无标题"))
        source = str(article.get("source", "未知"))
        score = float(item.get("total_score", 0) or 0)
        summary = str(item.get("summary", "") or "")
        link = get_report_link(item, base_url)

        lines.extend(
            [
                f"**{escape_markdown_v2(f'{index}. {title}')}**",
                f"- 评分：{score:.1f}/10",
                f"- 来源：{escape_markdown_v2(source)}",
                f"- 核心看点：{escape_markdown_v2(summary)}",
                f"- {_link('在线阅读', link)}",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            escape_markdown_v2("本报告由 AI Frontier Knowledge Agent 自动生成"),
        ]
    )
    content = "\n".join(lines)
    if len(content.encode("utf-8")) <= 4096:
        return content

    print("   ⚠️ 消息超过 4096 字节，改为只推送前 3 篇")
    return "\n".join(lines[:5] + lines[5:20] + lines[-2:])[:4096]


def send_markdown(content: str) -> bool:
    try:
        response = requests.post(config.WECOM_WEBHOOK, json={"msgtype": "markdown", "markdown": {"content": content}}, timeout=30)
        data = response.json()
        if response.status_code == 200 and data.get("errcode") == 0:
            return True
        print(f"   ❌ 企业微信 Markdown 失败: {response.text[:500]}")
    except Exception as exc:
        print(f"   ❌ 企业微信 Markdown 异常: {exc}")
    return False


def _webhook_key(webhook: str) -> str:
    match = re.search(r"[?&]key=([^&]+)", webhook or "")
    return match.group(1) if match else ""


def upload_file(file_path: str):
    key = _webhook_key(config.WECOM_WEBHOOK)
    if not key:
        return None, {"error": "WECOM_WEBHOOK 中没有 key"}
    try:
        with open(file_path, "rb") as file_obj:
            response = requests.post("https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media", params={"key": key, "type": "file"}, files={"media": (os.path.basename(file_path), file_obj, "application/octet-stream")}, timeout=60)
        data = response.json()
        return (data.get("media_id") if data.get("errcode") == 0 else None), data
    except Exception as exc:
        return None, {"error": str(exc)}


def send_file(media_id: str) -> bool:
    try:
        response = requests.post(config.WECOM_WEBHOOK, json={"msgtype": "file", "file": {"media_id": media_id}}, timeout=30)
        data = response.json()
        return response.status_code == 200 and data.get("errcode") == 0
    except Exception as exc:
        print(f"   ❌ 企业微信文件消息异常: {exc}")
        return False


def _build_classic_content(items: List[Dict]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"### 📄 AI 前沿日报 - {today}", "", f"> 处理文章：{len(items)} 篇", ""]
    for index, item in enumerate(items[:10], start=1):
        article = item.get("article", {})
        title = str(article.get("title", "无标题"))
        source = str(article.get("source", "未知"))
        score = float(item.get("total_score", 0) or 0)
        summary = str(item.get("summary", "") or "")[:300]
        preview = get_report_link(item, config.REPORT_BASE_URL)
        download = str(item.get("_download_url", "") or "")
        lines.extend([f"**{index}. {title}**", f"> 方向：<font color=\"info\">{source}</font>", f"评分：{score:.1f}/10", summary, f"[在线预览]({preview})"])
        if download:
            lines.append(f"[下载报告]({download})")
        lines.append("")
    return "\n".join(lines)[:4000]


def send_to_wecom(items: List[Dict]) -> bool:
    if not validate_config():
        return False
    cos_enabled = bool(config.COS_SECRET_ID and config.COS_SECRET_KEY and config.COS_BUCKET)
    if cos_enabled:
        from output.generator import upload_report_links
        for item in items:
            output_path = str(item.get("_output_path", "") or "")
            if not output_path or not os.path.isfile(output_path):
                print(f"   ❌ COS 上传失败：报告文件不存在 {output_path}")
                return False
            try:
                item["_preview_url"], item["_download_url"] = upload_report_links(output_path)
            except Exception as exc:
                print(f"   ❌ COS 上传失败: {exc}")
                return False
    else:
        print("   ⚠️ COS 未配置，使用 REPORT_BASE_URL 链接")
    content = _build_classic_content(items) if cos_enabled else _build_content(items, config.REPORT_BASE_URL)
    success = send_markdown(content) if cos_enabled else send_markdown_v2(content)
    if not success:
        return False
    if cos_enabled:
        time.sleep(4)
        for item in items:
            media_id, detail = upload_file(item["_output_path"])
            if not media_id:
                print(f"   ❌ 上传文件失败: {detail}")
                return False
            time.sleep(4)
            if not send_file(media_id):
                return False
    print("   ✅ 推送成功")
    return True