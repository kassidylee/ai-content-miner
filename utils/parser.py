# utils/parser.py
"""
文章解析工具（唯一权威实现）
支持：.md 文件解析、MediaCrawler 数据标准化、统一数据加载入口、递归加载子目录
"""
import os
import re
import json
from datetime import datetime
from typing import Dict, List

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
            except:
                continue

    return metadata


def read_articles_from_folder() -> List[Dict]:
    articles = []
    articles_dir = "./articles"
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


# ---------- MediaCrawler 数据标准化 ----------
def normalize_article(raw: Dict) -> Dict:
    title = (
        raw.get("title") or raw.get("标题") or raw.get("note_title") or
        raw.get("name") or raw.get("nickname") or raw.get("display_name") or "无标题"
    )

    content = (
        raw.get("content") or raw.get("正文") or raw.get("description") or
        raw.get("note_content") or raw.get("text") or raw.get("desc") or raw.get("raw_text") or ""
    )
    if isinstance(content, list):
        content = "\n".join([str(c) for c in content])
    if isinstance(content, dict):
        content = content.get("text", content.get("content", str(content)))

    source = (
        raw.get("source") or raw.get("平台") or raw.get("platform") or
        raw.get("platform_name") or raw.get("site") or "未知"
    )

    url = (
        raw.get("url") or raw.get("链接") or raw.get("note_url") or
        raw.get("link") or raw.get("share_url") or raw.get("web_url") or ""
    )

    author = (
        raw.get("author") or raw.get("作者") or raw.get("nickname") or
        raw.get("user_name") or raw.get("username") or raw.get("user_id") or
        raw.get("uid") or raw.get("author_name") or ""
    )

    likes = (
        raw.get("likes") or raw.get("点赞数") or raw.get("like_count") or
        raw.get("liked_count") or raw.get("like_num") or raw.get("like_cnt") or 0
    )

    comments = (
        raw.get("comments") or raw.get("评论数") or raw.get("comment_count") or
        raw.get("comment_num") or raw.get("comment_cnt") or 0
    )

    collects = (
        raw.get("collects") or raw.get("收藏数") or raw.get("collect_count") or
        raw.get("collected_count") or 0
    )

    shares = (
        raw.get("shares") or raw.get("分享数") or raw.get("share_count") or 0
    )

    publish_time = (
        raw.get("publish_time") or raw.get("发布时间") or raw.get("time") or
        raw.get("created_at") or raw.get("create_time") or raw.get("post_time") or
        raw.get("date") or None
    )

    if isinstance(publish_time, str):
        for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"]:
            try:
                publish_time = datetime.strptime(publish_time, fmt)
                break
            except:
                continue

    if isinstance(publish_time, (int, float)):
        try:
            if publish_time > 10000000000:
                publish_time = datetime.fromtimestamp(publish_time / 1000)
            else:
                publish_time = datetime.fromtimestamp(publish_time)
        except:
            publish_time = None

    return {
        "title": str(title) if title else "无标题",
        "content": str(content) if content else "",
        "source": str(source) if source else "未知",
        "url": str(url) if url else "",
        "publish_time": publish_time,
        "author": str(author) if author else "",
        "likes": int(likes) if likes else 0,
        "comments": int(comments) if comments else 0,
        "collects": int(collects) if collects else 0,
        "shares": int(shares) if shares else 0,
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

    if "公众号" in source or "wechat" in source_lower or "微信" in source or "mp.weixin" in source_lower:
        return "微信公众号"

    # 预留扩展
    if "x.com" in source_lower or "twitter" in source_lower:
        return "X (Twitter)"
    if "youtube" in source_lower or "youtu.be" in source_lower:
        return "YouTube"
    if "reddit" in source_lower:
        return "Reddit"

    return "未知"


# ---------- 统一数据加载入口 ----------
def load_articles() -> List[Dict]:
    articles = []

    # 1. 从 data/ 递归加载
    if os.path.exists(config.DATA_DIR):
        for root, dirs, files in os.walk(config.DATA_DIR):
            for filename in files:
                filepath = os.path.join(root, filename)

                if filename.endswith(".json"):
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            data = json.load(f)

                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict):
                                    articles.append(normalize_article(item))
                        elif isinstance(data, dict):
                            list_keys = ["data", "list", "items", "notes", "articles", "result", "results", "records", "feeds"]
                            found_list = False
                            for key in list_keys:
                                if key in data and isinstance(data[key], list):
                                    for item in data[key]:
                                        if isinstance(item, dict):
                                            articles.append(normalize_article(item))
                                    found_list = True
                                    break
                            if not found_list:
                                articles.append(normalize_article(data))
                    except Exception as e:
                        print(f"   ⚠️ 加载失败: {filename} - {e}")

                elif filename.endswith(".jsonl"):
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if line:
                                    try:
                                        articles.append(normalize_article(json.loads(line)))
                                    except:
                                        continue
                    except Exception as e:
                        print(f"   ⚠️ JSONL 读取失败: {filename} - {e}")

                elif filename.endswith(".csv"):
                    try:
                        import pandas as pd
                        df = pd.read_csv(filepath, encoding="utf-8")
                        for _, row in df.iterrows():
                            articles.append(normalize_article(row.to_dict()))
                    except ImportError:
                        pass
                    except Exception as e:
                        print(f"   ⚠️ CSV 读取失败: {filename} - {e}")

    # 2. 回退到 articles/
    if not articles:
        print("   ℹ️ 未找到爬虫数据，尝试从 ./articles/ 加载手动文章...")
        articles = read_articles_from_folder()

    # 3. 应用 CRAWL_LIMIT
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