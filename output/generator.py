# output/generator.py
"""
多模式输出生成器
短内容（<500字）：纯文本卡片 (.txt)
中等/长内容（>=500字）：完整 HTML 研报 (.html)
"""
import os
import re
from typing import Dict
from openai import OpenAI

import config

client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)


def generate_output(item: Dict) -> str:
    article = item.get("article", {})
    content = article.get("content", "")
    word_count = len(content)

    if word_count < config.SHORT_CONTENT_LIMIT:
        return generate_card(item)
    else:
        return generate_report(item)


def generate_card(item: Dict) -> str:
    article = item.get("article", {})
    title = article.get("title", "无标题")
    source = article.get("source", "未知")
    score = item.get("total_score", 0)
    summary = item.get("summary", "")
    dims = item.get("dimensions", [])
    scores = item.get("scores", [])
    url = article.get("url", "")

    lines = [
        f"# {title}",
        "",
        f"来源：{source}  |  评分：{score:.1f}/10",
        "",
        f"核心价值：{summary}",
        "",
        "维度评分：",
    ]
    for d, s in zip(dims, scores):
        lines.append(f"  - {d}：{s:.1f}/2")

    lines.append("")
    lines.append("建议：本文为短内容，已提取核心观点。如需深度分析，建议查找原始出处。")
    if url:
        lines.append(f"原文链接：{url}")

    content = "\n".join(lines)

    filename = sanitize_filename(title) + ".txt"
    filepath = os.path.join(config.REPORT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    item["_output_path"] = filepath
    return filepath


def generate_report(item: Dict) -> str:
    article = item.get("article", {})
    title = article.get("title", "无标题")
    content = article.get("content", "")
    source = article.get("source", "未知")
    url = article.get("url", "")
    score = item.get("total_score", 0)
    dims = item.get("dimensions", ["相关性", "创新性", "可复现性", "声誉", "社区热度"])
    scores = item.get("scores", [0] * len(dims))
    summary = item.get("summary", "")
    word_count = len(content)
    is_second_hand = item.get("is_second_hand", False)
    original_source = item.get("original_source", "")

    score_map = dict(zip(dims, scores)) if len(dims) == len(scores) else {}

    filename = sanitize_filename(title) + ".html"
    filepath = os.path.join(config.REPORT_DIR, filename)

    prompt = f"""请为以下文章生成一份深度分析研报（HTML 格式）。

**核心受众**：AI Agent 研究者、开发者和爱好者。

**信源标注**：原文用 📌，你的总结/批注用 📝。

文章标题：{title}
来源：{source}
原文链接：{url}
综合评分：{score:.1f}/10
字数：{word_count}
核心价值：{summary}
维度评分：{', '.join([f'{d}={s:.1f}' for d, s in score_map.items()])}
{"⚠️ 本文疑似转载/二手信息，原始出处：" + original_source if is_second_hand else ""}

文章全文：
{content}

**生成要求**：

1. **评分卡放在最前面**，包含：
   - SVG 五边形雷达图（五个顶点均匀分布在圆周上，间隔72度）
   - 详细评分表（维度、得分、权重说明）

2. **简报**：背景、核心内容、一句话总结、原文出处

3. **深度精读**：
   - 核心观点拆解（📌 和 📝 混合）
   - 技术细节解读（📌 和 📝 混合）
   - 代码解析（如有，逐段拆解逻辑和设计思路）
   - 应用场景与价值（📝）
   - 局限性与风险点（📝）

{"4. **重要**：在开头用红色标注「本文疑似转载/二手信息，建议查询原始出处」" if is_second_hand else ""}

**格式要求**：
- 完整 HTML，包含内联 CSS
- 直接输出 HTML，不要用 markdown 代码块包裹
- 字体：'Source Sans 3', 'Noto Sans SC', sans-serif
- 配色：学术冷淡风（灰白蓝基调）
- 页面大标题使用文章原标题
- 严禁：自我指涉、模糊表述、注水废话
"""

    try:
        response = client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是专业的技术分析师，擅长生成精炼且有深度的研报。"},
                {"role": "user", "content": prompt}
            ],
            temperature=config.REPORT_TEMPERATURE,
            max_tokens=7000
        )

        html = response.choices[0].message.content or ""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        item["_output_path"] = filepath
        return filepath

    except Exception as e:
        print(f"   ❌ 研报生成失败: {e}")
        fallback_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>{title}</title></head>
<body>
<h1>{title}</h1>
<p>研报生成失败：{e}</p>
<p>来源：{source}</p>
<p>评分：{score:.1f}/10</p>
<p>核心价值：{summary}</p>
<hr>
<pre>{content[:2000]}...</pre>
</body>
</html>"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(fallback_html)

        item["_output_path"] = filepath
        return filepath


def sanitize_filename(title: str) -> str:
    safe = re.sub(r'[^\w\s\u4e00-\u9fff]', '', title)
    safe = safe.strip()[:40].replace(' ', '_')
    return safe or "未命名"