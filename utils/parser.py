# utils/parser.py
"""
文章解析工具（唯一权威实现）
支持：.md 文件解析、多采集器数据标准化、显式内容文件加载
"""
import os
import re
import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

import config


# ---------- .md 文件解析 ----------
def parse_metadata(content: str) -> Dict:
    metadata = {"title": "", "source": "", "url": "", "publish_time": None, "body": content}

    title_match = re.search(r'^#\s*(.+)$', content, re.MULTILINE)
    if title_match:
        metadata["title"] = title_match.group(1).strip()

    source_match = re.search(r'^来源[：:]\s*(.+)$', content, re.MULTILINE)
    if source_match:
        metadata["source"] = source_match.group(1).strip()

    url_match = re.search(r'^链接[：:]\s*(.+)$', content, re.MULTILINE)
    if url_match:
        metadata["url"] = url_match.group(1).strip()

    time_match = re.search(r'^发布时间[：:]\s*(.+)$', content, re.MULTILINE)
    if time_match:
        time_str = time_match.group(1).strip()
        for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"]:
            try:
                metadata["publish_time"] = datetime.strptime(time_str, fmt)
                break
            except ValueError:
                continue

    return metadata


def read_articles_from_folder() -> List[Dict]:
    articles = []
    articles_dir = config.ARTICLES_DIR
    if not os.path.exists(articles_dir):
        os.makedirs(articles_dir, exist_ok=True)
        return articles

    for filename in os.listdir(articles_dir):
        if not filename.endswith((".md", ".txt")):
            continue

        filepath = os.path.join(articles_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            meta = parse_metadata(content)
            title = meta["title"] or os.path.splitext(filename)[0]

            articles.append({
                "title": title,
                "content": meta["body"],
                "source": meta["source"] or "未知",
                "url": meta["url"] or "",
                "publish_time": meta["publish_time"],
                "filename": filename,
                "filepath": filepath
            })
        except Exception as e:
            print(f"   ⚠️ 读取失败: {filename} - {e}")

    return articles


# ---------- 采集器数据标准化 ----------
def _coerce_count(value: object) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip().replace(",", "")
    multipliers = {"万": 10_000, "w": 10_000, "k": 1_000}
    multiplier = 1
    if text and text[-1].lower() in multipliers:
        multiplier = multipliers[text[-1].lower()]
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except (TypeError, ValueError):
        return 0


def normalize_article(raw: Dict, platform: str = "") -> Dict:
    """将各采集器的内容记录转换为项目统一格式。"""
    title = (
        raw.get("title") or raw.get("标题") or raw.get("note_title") or
        raw.get("full_name") or raw.get("name") or raw.get("nickname") or
        raw.get("display_name") or "无标题"
    )

    content = (
        raw.get("content") or raw.get("正文") or raw.get("description") or
        raw.get("note_content") or raw.get("content_text") or raw.get("text") or
        raw.get("desc") or raw.get("raw_text") or ""
    )
    if isinstance(content, list):
        content = "\n".join([str(c) for c in content])
    if isinstance(content, dict):
        content = content.get("text", content.get("content", str(content)))

    source = (
        raw.get("source") or raw.get("平台") or raw.get("platform") or
        raw.get("platform_name") or raw.get("site") or platform or "未知"
    )

    url = (
        raw.get("url") or raw.get("链接") or raw.get("note_url") or
        raw.get("content_url") or raw.get("link") or raw.get("share_url") or
        raw.get("web_url") or raw.get("html_url") or ""
    )

    author = (
        raw.get("author") or raw.get("作者") or raw.get("nickname") or
        raw.get("user_nickname") or raw.get("user_name") or raw.get("username") or
        raw.get("user_id") or raw.get("uid") or raw.get("author_name") or
        (raw.get("owner") or {}).get("login", "") or ""
    )

    likes = (
        raw.get("likes") or raw.get("点赞数") or raw.get("like_count") or
        raw.get("liked_count") or raw.get("voteup_count") or raw.get("like_num") or
        raw.get("like_cnt") or raw.get("stars") or
        raw.get("stargazers_count") or 0
    )

    comments = (
        raw.get("comments") or raw.get("评论数") or raw.get("comment_count") or
        raw.get("comment_num") or raw.get("comment_cnt") or
        raw.get("open_issues") or raw.get("open_issues_count") or 0
    )

    collects = (
        raw.get("collects") or raw.get("收藏数") or raw.get("collect_count") or
        raw.get("collected_count") or raw.get("forks") or
        raw.get("forks_count") or 0
    )

    shares = (
        raw.get("shares") or raw.get("分享数") or raw.get("share_count") or
        raw.get("watchers") or raw.get("watchers_count") or 0
    )

    publish_time = (
        raw.get("publish_time") or raw.get("发布时间") or raw.get("time") or
        raw.get("created_at") or raw.get("created_time") or raw.get("create_time") or
        raw.get("post_time") or raw.get("date") or None
    )

    if isinstance(publish_time, str):
        original_publish_time = publish_time
        try:
            publish_time = datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
        except ValueError:
            for fmt in [
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M",
                "%Y/%m/%d",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%fZ",
            ]:
                try:
                    publish_time = datetime.strptime(original_publish_time, fmt)
                    break
                except ValueError:
                    continue

    if isinstance(publish_time, (int, float)):
        try:
            if publish_time > 10000000000:
                publish_time = datetime.fromtimestamp(publish_time / 1000)
            else:
                publish_time = datetime.fromtimestamp(publish_time)
        except (OSError, OverflowError, ValueError):
            publish_time = None

    normalized_source = source_classify(str(source))
    if normalized_source == "未知" and source and source != "未知":
        normalized_source = str(source)

    return {
        "title": str(title) if title else "无标题",
        "content": str(content) if content else "",
        "source": normalized_source,
        "url": str(url) if url else "",
        "publish_time": publish_time,
        "author": str(author) if author else "",
        "likes": _coerce_count(likes),
        "comments": _coerce_count(comments),
        "collects": _coerce_count(collects),
        "shares": _coerce_count(shares),
        "raw": raw
    }


# ---------- 来源分类 ----------
def source_classify(source: str) -> str:
    if not source or source == "未知":
        return "未知"

    source_lower = source.lower()

    if "小红书" in source or "xiaohongshu" in source_lower or "xhs" in source_lower:
        return "小红书"

    if "知乎" in source or "zhihu" in source_lower:
        return "知乎"

    if (
        "公众号" in source
        or "wechat" in source_lower
        or "微信" in source
        or "mp.weixin" in source_lower
    ):
        return "微信公众号"

    # 预留扩展
    if "x.com" in source_lower or "twitter" in source_lower:
        return "X (Twitter)"
    if "youtube" in source_lower or "youtu.be" in source_lower:
        return "YouTube"
    if "reddit" in source_lower:
        return "Reddit"
    if "github" in source_lower or "git hub" in source_lower:
        return "GitHub"

    return "未知"


# ---------- 统一数据加载入口 ----------
PathLike = Union[str, os.PathLike]


def _append_json_data(data: object, articles: List[Dict], platform: str) -> None:
    if isinstance(data, list):
        articles.extend(
            normalize_article(item, platform) for item in data if isinstance(item, dict)
        )
        return
    if not isinstance(data, dict):
        return

    list_keys = [
        "data", "list", "items", "notes", "articles", "result", "results",
        "records", "feeds",
    ]
    for key in list_keys:
        if isinstance(data.get(key), list):
            articles.extend(
                normalize_article(item, platform)
                for item in data[key]
                if isinstance(item, dict)
            )
            return
    articles.append(normalize_article(data, platform))


def _load_article_file(filepath: Path, articles: List[Dict], platform: str) -> None:
    if filepath.suffix == ".json":
        with filepath.open("r", encoding="utf-8") as file_obj:
            _append_json_data(json.load(file_obj), articles, platform)
        return

    if filepath.suffix == ".jsonl":
        with filepath.open("r", encoding="utf-8") as file_obj:
            for line_number, line in enumerate(file_obj, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(
                        f"   ⚠️ 跳过无效 JSONL：{filepath.name}:{line_number} - {exc}"
                    )
                    continue
                if isinstance(data, dict):
                    articles.append(normalize_article(data, platform))
        return

    if filepath.suffix == ".csv":
        with filepath.open("r", encoding="utf-8-sig", newline="") as file_obj:
            for row in csv.DictReader(file_obj):
                articles.append(normalize_article(dict(row), platform))


def load_articles(
    data_files: Optional[Iterable[PathLike]] = None,
    platform: str = "",
    allow_manual_fallback: bool = True,
) -> List[Dict]:
    """只加载显式传入的本次爬虫内容文件。

    不再递归扫描 ``data/``，以免把历史运行、评论或创作者记录误当成文章。
    手动文章回退仅在调用方明确允许时启用。
    """
    articles: List[Dict] = []

    for raw_path in data_files or ():
        filepath = Path(raw_path)
        if "_comments_" in filepath.name or "_creators_" in filepath.name:
            print(f"   ⚠️ 跳过非内容文件: {filepath.name}")
            continue
        if filepath.suffix not in {".json", ".jsonl", ".csv"}:
            print(f"   ⚠️ 跳过不支持的数据文件: {filepath}")
            continue
        try:
            _load_article_file(filepath, articles, platform)
        except (OSError, json.JSONDecodeError, csv.Error) as exc:
            print(f"   ⚠️ 加载失败: {filepath.name} - {exc}")

    if not articles and allow_manual_fallback:
        print("   ℹ️ 未找到本次爬虫数据，尝试从 ./articles/ 加载手动文章...")
        articles = read_articles_from_folder()

    # 应用本项目下游处理数量限制。
    limit = getattr(config, 'CRAWL_LIMIT', 0)
    if limit > 0 and len(articles) > limit:
        print(f"   📊 应用数量限制: {len(articles)} → {limit}")
        articles = articles[:limit]

    return articles


# ---------- 工具函数 ----------
def extract_summary(content: str, max_length: int = 200) -> str:
    if not content:
        return ""
    plain = re.sub(r'[#*`_~>\[\]()|]', '', content)
    plain = re.sub(r'\s+', ' ', plain).strip()
    if len(plain) <= max_length:
        return plain
    return plain[:max_length] + "..."


def extract_keywords(content: str, max_count: int = 5) -> List[str]:
    if not content:
        return []

    plain = re.sub(r'[#*`_~>\[\]()|]', '', content)
    words = re.findall(r'[\u4e00-\u9fa5a-zA-Z]+', plain)

    stopwords = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
                 "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
                 "自己", "这", "那", "它", "他", "她", "对", "从", "为", "与", "或", "但", "而"}

    freq = {}
    for w in words:
        if len(w) >= 2 and w not in stopwords:
            freq[w] = freq.get(w, 0) + 1

    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:max_count]]


def count_words(text: str) -> int:
    if not text:
        return 0
    chinese_chars = re.findall(r'[\u4e00-\u9fa5]', text)
    english_words = re.findall(r'[a-zA-Z]+', text)
    return len(chinese_chars) + len(english_words)
