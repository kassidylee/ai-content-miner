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
    """从 .md 文件头部解析元信息"""
    metadata = {
        "title": "",
        "source": "",
        "url": "",
        "publish_time": None,
        "body": content
    }

    # 提取标题
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
    """从 ./articles/ 文件夹读取所有 .md 文件"""
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
            articles.append({
                "title": meta["title"] or os.path.splitext(filename)[0],
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
    """将 MediaCrawler 的数据格式标准化为内部格式"""
    # MediaCrawler 各平台返回字段有所不同，做兼容处理
    return {
        "title": raw.get("title", raw.get("标题", raw.get("note_title", "无标题"))),
        "content": raw.get("content", raw.get("正文", raw.get("description", raw.get("note_content", "")))),
        "source": raw.get("source", raw.get("平台", raw.get("platform", "未知"))),
        "url": raw.get("url", raw.get("链接", raw.get("note_url", ""))),
        "publish_time": raw.get("publish_time", raw.get("发布时间", raw.get("time", None))),
        "author": raw.get("author", raw.get("作者", raw.get("nickname", ""))),
        "likes": raw.get("likes", raw.get("点赞数", raw.get("like_count", 0))),
        "comments": raw.get("comments", raw.get("评论数", raw.get("comment_count", 0))),
        "raw": raw
    }