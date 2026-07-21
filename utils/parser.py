# utils/parser.py
"""
文章解析工具
支持：
1. 从 ./articles/ 目录读取 .md 文件
2. MediaCrawler 数据标准化
"""
import os
import re
from datetime import datetime
from typing import Dict, List, Optional


def parse_metadata(content: str) -> Dict:
    """
    从 .md 文件头部解析元信息

    期望格式：
    # 标题
    来源：小红书
    链接：https://www.xiaohongshu.com/xxx
    发布时间：2026-07-20 10:00

    正文内容...
    """
    metadata = {
        "title": "",
        "source": "",
        "url": "",
        "publish_time": None,
        "body": content
    }

    # 提取标题（第一个 # 开头的行）
    title_match = re.search(r'^#\s*(.+)$', content, re.MULTILINE)
    if title_match:
        metadata["title"] = title_match.group(1).strip()

    # 提取来源
    source_match = re.search(r'^来源[：:]\s*(.+)$', content, re.MULTILINE)
    if source_match:
        metadata["source"] = source_match.group(1).strip()

    # 提取链接
    url_match = re.search(r'^链接[：:]\s*(.+)$', content, re.MULTILINE)
    if url_match:
        metadata["url"] = url_match.group(1).strip()

    # 提取发布时间
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
    """从 ./articles/ 文件夹读取所有 .md 或 .txt 文件"""
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

            # 如果没有解析到标题，用文件名
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


def normalize_article(raw: Dict) -> Dict:
    """
    将 MediaCrawler 的数据格式标准化为内部格式

    MediaCrawler 各平台返回字段有所不同（小红书、知乎、微信公众号等），
    做兼容处理统一字段名。
    """
    # 尝试从 raw 中提取 title
    title = (
        raw.get("title") or
        raw.get("标题") or
        raw.get("note_title") or
        raw.get("name") or
        "无标题"
    )

    # 尝试提取 content
    content = (
        raw.get("content") or
        raw.get("正文") or
        raw.get("description") or
        raw.get("note_content") or
        raw.get("text") or
        ""
    )

    # 尝试提取 source/platform
    source = (
        raw.get("source") or
        raw.get("平台") or
        raw.get("platform") or
        "未知"
    )

    # 尝试提取 url
    url = (
        raw.get("url") or
        raw.get("链接") or
        raw.get("note_url") or
        raw.get("link") or
        ""
    )

    # 尝试提取作者
    author = (
        raw.get("author") or
        raw.get("作者") or
        raw.get("nickname") or
        raw.get("user_name") or
        raw.get("username") or
        ""
    )

    # 尝试提取互动数据
    likes = (
        raw.get("likes") or
        raw.get("点赞数") or
        raw.get("like_count") or
        raw.get("liked_count") or
        0
    )

    comments = (
        raw.get("comments") or
        raw.get("评论数") or
        raw.get("comment_count") or
        0
    )

    # 尝试提取时间
    publish_time = (
        raw.get("publish_time") or
        raw.get("发布时间") or
        raw.get("time") or
        raw.get("created_at") or
        None
    )

    # 如果 publish_time 是字符串，尝试解析
    if isinstance(publish_time, str):
        for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"]:
            try:
                publish_time = datetime.strptime(publish_time, fmt)
                break
            except:
                continue

    return {
        "title": title,
        "content": content,
        "source": source,
        "url": url,
        "publish_time": publish_time,
        "author": author,
        "likes": likes,
        "comments": comments,
        "raw": raw
    }


def source_classify(source: str) -> str:
    """
    将来源分类为：小红书 / 知乎 / 微信公众号
    """
    source_lower = source.lower()

    if "小红书" in source or "xiaohongshu" in source_lower:
        return "小红书"
    elif "知乎" in source or "zhihu" in source_lower:
        return "知乎"
    elif "公众号" in source or "wechat" in source_lower or "微信" in source:
        return "微信公众号"
    else:
        return "微信公众号"