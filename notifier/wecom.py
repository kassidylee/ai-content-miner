# notifier/wecom.py
import requests
from datetime import datetime
import config


def send_markdown_v2(content: str) -> bool:
    payload = {"msgtype": "markdown_v2", "markdown_v2": {"content": content}}
    try:
        resp = requests.post(config.WECOM_WEBHOOK, json=payload, timeout=10)
        return resp.status_code == 200 and resp.json().get('errcode') == 0
    except:
        return False


def send_to_wecom(items: list) -> bool:
    if not config.WECOM_WEBHOOK:
        print("   ⚠️ 未配置 Webhook")
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

    for idx, item in enumerate(items[:10]):  # 最多展示10篇
        article = item.get("article", {})
        title = article.get("title", "无标题")
        score = item.get("total_score", 0)
        summary = item.get("summary", "")
        safe_title = re.sub(r'[^\w\s\u4e00-\u9fff]', '', title)[:40].replace(' ', '_') or "未命名"
        link = f"{base_url.rstrip('/')}/{safe_title}.html"

        lines.append(f"**{idx+1}. {title}**")
        lines.append(f"- 评分：{score:.1f}/10")
        lines.append(f"- 核心看点：{summary}")
        lines.append(f"- 📖 [在线阅读]({link})")
        lines.append("")

    lines.append("---")
    lines.append("*本报告由 AI Frontier Knowledge Agent 自动生成*")

    return send_markdown_v2("\n".join(lines))