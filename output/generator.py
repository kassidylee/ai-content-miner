# output/generator.py
"""
报告输出生成器：所有成果统一生成完整 HTML 研报，并同步上传到腾讯云 COS。
"""
import hashlib
import os
import re
import time
from datetime import datetime
from typing import Dict
from openai import OpenAI

import config

client = OpenAI(
    api_key=config.API_KEY,
    base_url=config.BASE_URL,
    timeout=config.REPORT_TIMEOUT_SECONDS,
    max_retries=0,
)


def _report_retry_delay(exc: Exception, attempt: int) -> int:
    """Return a conservative delay for retryable upstream report failures."""
    status_code = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    retry_after = body.get("retry_after") if isinstance(body, dict) else None

    if isinstance(retry_after, (int, float)) and retry_after > 0:
        return int(retry_after)
    if status_code == 524 or "524" in str(exc):
        return 120
    return min(config.REPORT_RETRY_BACKOFF_SECONDS * attempt, 300)


def _is_retryable_report_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    text = str(exc).lower()
    return (
        status_code in {408, 429, 500, 502, 503, 504, 524}
        or "524" in text
        or "timed out" in text
        or "timeout" in text
        or "readtimeout" in text
    )


def _html_escape(value: object) -> str:
    import html
    return html.escape(str(value or ""))


def _build_radar_svg(dimensions: list, scores: list) -> str:
    """Build a deterministic five-axis radar chart from 0-2 scores."""
    import math

    labels = [str(value)[:12] for value in dimensions[:5]]
    values = [max(0.0, min(2.0, float(value))) for value in scores[:5]]
    labels.extend([f"维度 {index}" for index in range(len(labels) + 1, 6)])
    values.extend([0.0] * (5 - len(values)))
    center, radius = 120.0, 86.0
    angles = [-90.0 + index * 72.0 for index in range(5)]

    def point(value: float, angle: float) -> str:
        scale = radius * value / 2.0
        radians = math.radians(angle)
        return f"{center + scale * math.cos(radians):.1f},{center + scale * math.sin(radians):.1f}"

    rings = [
        f'<polygon points="{" ".join(point(level, angle) for angle in angles)}" class="radar-ring" />'
        for level in (0.5, 1.0, 1.5, 2.0)
    ]
    axes = []
    label_nodes = []
    for label, angle in zip(labels, angles):
        end_x, end_y = point(2.0, angle).split(",")
        label_x, label_y = point(2.28, angle).split(",")
        anchor = "end" if float(label_x) < center - 10 else "start" if float(label_x) > center + 10 else "middle"
        axes.append(f'<line x1="{center}" y1="{center}" x2="{end_x}" y2="{end_y}" class="radar-axis" />')
        label_nodes.append(f'<text x="{label_x}" y="{label_y}" text-anchor="{anchor}" class="radar-label">{_html_escape(label)}</text>')

    area = " ".join(point(value, angle) for value, angle in zip(values, angles))
    return (
        '<div class="radar-card"><h3>五维评分雷达图（满分 2 分）</h3>'
        '<svg viewBox="0 0 240 240" role="img" aria-label="五维评分雷达图">'
        '<style>.radar-ring{fill:none;stroke:#cbd5e1;stroke-width:1}.radar-axis{stroke:#cbd5e1;stroke-width:1}.radar-area{fill:#3b82f655;stroke:#2563eb;stroke-width:2}.radar-label{font-size:9px;fill:#334155}</style>'
        + "".join(rings) + "".join(axes)
        + f'<polygon points="{area}" class="radar-area" />'
        + "".join(label_nodes) + "</svg></div>"
    )


def _insert_standard_radar(html: str, dimensions: list, scores: list) -> str:
    radar = _build_radar_svg(dimensions, scores)
    if "[[STANDARD_RADAR]]" in html:
        return html.replace("[[STANDARD_RADAR]]", radar)
    marker = "</body>"
    index = html.lower().rfind(marker)
    return html[:index] + radar + html[index:] if index >= 0 else radar + html


def _build_report_prompt(
    title: str,
    source: str,
    url: str,
    score: float,
    word_count: int,
    summary: str,
    score_map: Dict,
    report_content: str,
    truncation_notice: str,
    evidence_block: str,
    is_second_hand: bool,
    original_source: str,
    compact: bool,
) -> str:
    output_length = "1200–1800" if compact else "3000–4500"
    detail_requirement = (
        "聚焦结论、关键技术机制、证据和风险，不展开重复说明。"
        if compact
        else "不要为了简短而省略技术机制、证据、对比、实施步骤和风险分析。"
    )
    return f"""请为以下文章生成一份深度分析研报（HTML 格式）。

**核心受众**：AI Agent 研究者、开发者和爱好者。

**信源标注**：原文用 📌，你的总结/批注用 📝。

文章标题：{title}
来源：{source}
原文链接：{url}
综合评分：{score:.1f}/10
字数：{word_count}
核心价值：{summary}
维度评分：{', '.join([f'{dimension}={value:.1f}' for dimension, value in score_map.items()])}
{"⚠️ 本文疑似转载/二手信息，原始出处：" + original_source if is_second_hand else ""}

文章全文：
{report_content}
{truncation_notice}

代码证据（仅可引用以下已读取文件；若为空则明确说明未核验）：
{evidence_block}

**生成要求**：

1. **评分卡放在最前面**，包含详细评分表（维度、得分、权重说明）。
2. **简报**：背景、核心内容、一句话总结、原文出处。
3. **深度精读**：核心观点拆解、技术细节解读、代码解析（如有）、应用价值、局限性与风险点。

**格式要求**：
- 输出正文约 {output_length} 字；{detail_requirement}
- 完整 HTML，包含内联 CSS；直接输出 HTML，不要使用 Markdown 代码块
- 雷达图位置必须只写占位符 `[[STANDARD_RADAR]]`；程序会根据真实五维分数统一插入
- 代码解析必须区分“原文/代码证据”和“分析判断”；只能逐段解读实际读取到的代码
- 若代码证据不足，明确说明未核验范围，不得根据 README 猜测实现细节
- 字体：'Source Sans 3', 'Noto Sans SC', sans-serif；配色：学术冷淡风
- 页面大标题使用文章原标题；严禁自我指涉、模糊表述和注水废话
"""


def generate_output(item: Dict) -> str:
    """生成 HTML 报告，并写入 COS 在线阅读/下载链接。"""
    local_path = generate_report(item)

    try:
        preview_url, download_url = upload_report_links(local_path, item)
        item["_preview_url"] = preview_url
        item["_download_url"] = download_url
        print(f"   ☁️ COS 上传成功: {os.path.basename(local_path)}")
    except Exception as exc:
        print(f"   ❌ COS 上传失败: {exc}")

    return local_path


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
    report_content = content[:config.REPORT_INPUT_MAX_CHARS]
    content_was_truncated = len(report_content) < word_count
    code_evidence = str(article.get("code_evidence", "") or "")
    evidence_manifest = article.get("evidence_manifest", [])
    evidence_block = (
        "已读取的代码证据文件："
        + ", ".join(str(path) for path in evidence_manifest)
        + "\n"
        + code_evidence[:config.REPORT_CODE_EVIDENCE_MAX_CHARS]
        if code_evidence
        else "未读取到代码文件；不得将 README 功能声明表述为已核验的实现细节。"
    )
    truncation_notice = (
        "\n注：原文较长，以上为用于生成本报告的前段内容。"
        if content_was_truncated
        else ""
    )
    is_second_hand = item.get("is_second_hand", False)
    original_source = item.get("original_source", "")

    score_map = dict(zip(dims, scores)) if len(dims) == len(scores) else {}

    filename = sanitize_filename(title) + ".html"
    filepath = os.path.join(config.REPORT_DIR, filename)

    prompt = _build_report_prompt(
        title,
        source,
        url,
        score,
        word_count,
        summary,
        score_map,
        report_content,
        truncation_notice,
        evidence_block,
        is_second_hand,
        original_source,
        compact=False,
    )

    try:
        response = None
        for attempt in range(1, config.REPORT_MAX_RETRIES + 1):
            compact = attempt > 1
            request_tokens = (
                min(config.REPORT_MAX_TOKENS, 2200)
                if compact
                else config.REPORT_MAX_TOKENS
            )
            attempt_prompt = (
                _build_report_prompt(
                    title,
                    source,
                    url,
                    score,
                    word_count,
                    summary,
                    score_map,
                    report_content[:3000],
                    "\n注：为提高生成可靠性，本次仅分析内容节选。",
                    evidence_block[:2500],
                    is_second_hand,
                    original_source,
                    compact=True,
                )
                if compact
                else prompt
            )
            try:
                response = client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是专业的技术分析师，擅长生成精炼且有深度的研报。",
                        },
                        {"role": "user", "content": attempt_prompt},
                    ],
                    temperature=config.REPORT_TEMPERATURE,
                    max_tokens=request_tokens,
                )
                break
            except Exception as exc:
                if (
                    not _is_retryable_report_error(exc)
                    or attempt == config.REPORT_MAX_RETRIES
                ):
                    raise
                delay = _report_retry_delay(exc, attempt)
                print(
                    f"   ⚠️ 研报请求失败（第 {attempt} 次）：{exc}；"
                    f"{delay} 秒后重试"
                )
                time.sleep(delay)

        if response is None:
            raise RuntimeError("研报请求未返回响应")

        html = response.choices[0].message.content or ""
        html = _insert_standard_radar(html, dims, scores)
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

def upload_report_links(local_path: str, item: Dict) -> tuple[str, str]:
    """Upload one report to COS and return preview/download presigned URLs."""
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as exc:
        raise RuntimeError(
            "缺少 cos-python-sdk-v5，请运行 pip install -r requirements.txt"
        ) from exc

    required = {
        "COS_SECRET_ID": config.COS_SECRET_ID,
        "COS_SECRET_KEY": config.COS_SECRET_KEY,
        "COS_REGION": config.COS_REGION,
        "COS_BUCKET": config.COS_BUCKET,
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise RuntimeError(f"COS 配置缺失: {', '.join(missing)}")

    path = os.path.abspath(local_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"报告文件不存在: {path}")

    filename = os.path.basename(path)
    article = item.get("article", {})
    identity = str(article.get("url") or article.get("title") or filename)
    content_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    timestamp = datetime.now()
    object_name = (
        f"{timestamp.strftime('%Y%m%d_%H%M%S')}_"
        f"{content_hash}_{filename}"
    )

    prefix = str(config.COS_PREFIX or "reports").strip("/")
    object_key = "/".join(
        part
        for part in (
            prefix,
            timestamp.strftime("%Y"),
            timestamp.strftime("%m"),
            timestamp.strftime("%d"),
            object_name,
        )
        if part
    )
    content_type = (
        "text/html; charset=utf-8"
        if filename.lower().endswith(".html")
        else "text/plain; charset=utf-8"
    )

    client = CosS3Client(
        CosConfig(
            Region=config.COS_REGION,
            SecretId=config.COS_SECRET_ID,
            SecretKey=config.COS_SECRET_KEY,
        )
    )
    with open(path, "rb") as file_obj:
        client.put_object(
            Bucket=config.COS_BUCKET,
            Key=object_key,
            Body=file_obj,
            ContentType=content_type,
        )

    expires = int(config.COS_PRESIGNED_EXPIRES)
    preview_url = client.get_presigned_url(
        Method="GET",
        Bucket=config.COS_BUCKET,
        Key=object_key,
        Expired=expires,
        Params={"response-content-disposition": "inline"},
    )
    download_url = client.get_presigned_url(
        Method="GET",
        Bucket=config.COS_BUCKET,
        Key=object_key,
        Expired=expires,
        Params={
            "response-content-disposition": f'attachment; filename="{filename}"',
            # HTML needs an unrenderable response type to force browser download.
            "response-content-type": "application/octet-stream",
        },
    )
    return preview_url, download_url