# output/generator.py
import os
import re
from datetime import datetime
from openai import OpenAI
import config

client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)


def generate_output(item: Dict) -> str:
    """根据内容长度和类型选择输出模式"""
    article = item.get("article", {})
    content = article.get("content", "")
    word_count = len(content)

    if word_count < config.SHORT_CONTENT_LIMIT:
        return generate_card(item)
    elif word_count < config.MEDIUM_CONTENT_LIMIT:
        return generate_brief(item)
    else:
        return generate_report(item)


def generate_card(item: Dict) -> str:
    """短内容卡片（纯文本）"""
    article = item.get("article", {})
    title = article.get("title", "无标题")
    source = article.get("source", "未知")
    score = item.get("total_score", 0)
    summary = item.get("summary", "")
    dims = item.get("dimensions", [])
    scores = item.get("scores", [])

    lines = [
        f"### {title}",
        "",
        f"**来源**: {source}  |  **评分**: {score:.1f}/10",
        f"**核心价值**: {summary}",
        "",
        "**维度评分**:",
    ]
    for d, s in zip(dims, scores):
        lines.append(f"  - {d}: {s:.1f}/2")
    lines.append("")
    lines.append("**建议**: 本文为短内容，已提取核心观点。如需深度分析，建议查找原始出处。")

    filename = sanitize_filename(title) + ".txt"
    filepath = os.path.join("./reports", filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return filepath


def generate_brief(item: Dict) -> str:
    """中等内容简报（简约 HTML）"""
    # 类似之前 generate_report 的简化版
    return generate_report(item)  # 复用完整报告逻辑


def generate_report(item: Dict) -> str:
    """长内容完整 HTML 研报"""
    article = item.get("article", {})
    title = article.get("title", "无标题")
    content = article.get("content", "")
    source = article.get("source", "未知")
    url = article.get("url", "")
    score = item.get("total_score", 0)
    dims = item.get("dimensions", [])
    scores = item.get("scores", [])
    summary = item.get("summary", "")
    is_second_hand = item.get("is_second_hand", False)
    original_source = item.get("original_source", "")

    safe_title = sanitize_filename(title)
    filename = f"{safe_title}.html"

    prompt = f"""请为以下文章生成一份深度分析研报（HTML 格式）。

**核心受众**：AI Agent 研究者、开发者和爱好者。

**信源标注**：原文用 📌，你的总结/批注用 📝。

文章标题：{title}
来源：{source}
原文链接：{url}
综合评分：{score:.1f}/10
维度评分：{', '.join([f'{d}={s:.1f}' for d, s in zip(dims, scores)])}
核心价值：{summary}
{"⚠️ 本文疑似转载/二手信息，原始出处：" + original_source if is_second_hand else ""}

文章全文：
{content}

**生成要求**：
1. 评分卡放在最前面（雷达图 SVG + 评分表）
2. 简报（背景、核心内容、一句话总结、原文出处）
3. 深度精读（观点拆解、技术细节、代码解析如有、应用场景、局限性）
{"4. 在开头用红色标注：本文疑似转载/二手信息，建议查询原始出处" if is_second_hand else ""}

直接输出 HTML，不要 markdown 代码块。"""

    try:
        response = client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是专业的技术分析师，擅长生成精炼且有深度的研报。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.25,
            max_tokens=5000
        )
        html = response.choices[0].message.content or ""
        filepath = os.path.join("./reports", filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        return filepath
    except Exception as e:
        print(f"   ❌ 研报生成失败: {e}")
        return ""


def sanitize_filename(title: str) -> str:
    safe = re.sub(r'[^\w\s\u4e00-\u9fff]', '', title)
    safe = safe.strip()[:40].replace(' ', '_')
    return safe or "未命名"