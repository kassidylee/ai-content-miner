# notifier/wecom.py
"""
企业微信推送模块
功能：配置校验、markdown_v2 消息发送、链接生成、错误记录
"""
import os
import re
import requests
from datetime import datetime
from typing import List, Dict

import config


def validate_config() -> bool:
    webhook = getattr(config, 'WECOM_WEBHOOK', '')
    if not webhook:
        print("   ❌ WECOM_WEBHOOK 未配置")
        return False

    placeholders = ["your-webhook-key", "your-key", "your-api-key-here", "sk-xxxxx", "example.com"]
    for p in placeholders:
        if p in webhook.lower():
            print(f"   ❌ WECOM_WEBHOOK 包含占位值 '{p}'，请配置真实地址")
            return False

    base_url = getattr(config, 'REPORT_BASE_URL', '')
    if "127.0.0.1" in base_url or "localhost" in base_url:
        print("   ⚠️ 注意：当前使用本地地址 127.0.0.1，员工可能无法访问")
        print("   📌 请在生产环境将 REPORT_BASE_URL 配置为内网/公网可访问地址")

    return True


def send_markdown_v2(content: str) -> bool:
    payload = {"msgtype": "markdown_v2", "markdown_v2": {"content": content}}

    try:
        resp = requests.post(config.WECOM_WEBHOOK, json=payload, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            if data.get('errcode') == 0:
                return True
            else:
                print(f"   ❌ 企业微信错误: errcode={data.get('errcode')}, errmsg={data.get('errmsg')}")
                print(f"   📄 响应内容: {resp.text[:300]}")
                return False
        else:
            print(f"   ❌ HTTP 错误: {resp.status_code}")
            print(f"   📄 响应内容: {resp.text[:300]}")
            return False

    except requests.exceptions.Timeout:
        print(f"   ❌ 连接超时（10s），请检查网络")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ 连接失败: {e}")
        return False
    except Exception as e:
        print(f"   ❌ 发送异常: {e}")
        return False


def sanitize_filename(title: str) -> str:
    safe = re.sub(r'[^\w\s\u4e00-\u9fff]', '', title)
    safe = safe.strip()[:40].replace(' ', '_')
    return safe or "未命名"


def get_report_link(item: Dict, base_url: str) -> str:
    output_path = item.get("_output_path", "")
    if not output_path:
        article = item.get("article", {})
        title = article.get("title", "无标题")
        safe_title = sanitize_filename(title)
        print(f"   ⚠️ 未找到输出路径，使用默认链接: {safe_title}.html")
        return f"{base_url.rstrip('/')}/{safe_title}.html"

    filename = os.path.basename(output_path)
    return f"{base_url.rstrip('/')}/{filename}"


def send_to_wecom(items: List[Dict]) -> bool:
    if not validate_config():
        return False

    base_url = config.REPORT_BASE_URL
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"# 📊 AI 前沿日报 - {today}",
        "",
        f"- **处理文章**：{len(items)} 篇",
        "",
        "## 🔥 深度挖掘队列",
        ""
    ]

    for idx, item in enumerate(items[:10]):
        article = item.get("article", {})
        title = article.get("title", "无标题")
        score = item.get("total_score", 0)
        summary = item.get("summary", "")
        source = article.get("source", "未知")

        link = get_report_link(item, base_url)

        lines.append(f"**{idx+1}. {title}**")
        lines.append(f"- 评分：{score:.1f}/10")
        lines.append(f"- 来源：{source}")
        lines.append(f"- 核心看点：{summary}")
        lines.append(f"- 📖 [在线阅读]({link})")
        lines.append("")

    lines.append("---")
    lines.append("*本报告由 AI Frontier Knowledge Agent 自动生成*")

    content = "\n".join(lines)

    if len(content.encode('utf-8')) > 4096:
        print(f"   ⚠️ 消息过长（{len(content.encode('utf-8'))} 字节），将截断至前 5 篇")
        lines_short = lines[:2] + lines[4:6] + ["", "---", "*本报告由 AI Frontier Knowledge Agent 自动生成*"]
        content = "\n".join(lines_short)

    print("   📤 发送企业微信消息...")
    success = send_markdown_v2(content)

    if success:
        print("   ✅ 推送成功")
    else:
        print("   ❌ 推送失败（详见上方错误信息）")

    return success