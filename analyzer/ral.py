# analyzer/ral.py
"""
RAL 来源识别模块
当前能力：arXiv ID、GitHub 仓库、转载声明检测、平台来源标记
暂未实现：自动抓取原始页面内容、缓存管理、循环重评
"""
import re
from typing import Dict, Optional

import config


def ral_pipeline(item: Dict) -> Dict:
    if not config.ENABLE_RETRIEVAL:
        return item

    article = item.get("article", {})
    content = article.get("content", "")
    url = article.get("url", "")

    item["original_source"] = ""
    item["source_type"] = ""
    item["is_second_hand"] = False

    # 1. arXiv
    arxiv_patterns = [
        r'arxiv\.org/abs/(\d+\.\d+)',
        r'arxiv\.org/pdf/(\d+\.\d+)',
        r'arXiv[:]?\s*(\d+\.\d+)',
    ]
    for pattern in arxiv_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            arxiv_id = match.group(1)
            item["original_source"] = f"https://arxiv.org/abs/{arxiv_id}"
            item["source_type"] = "arXiv 论文"
            item["is_second_hand"] = True
            return item

    # 2. GitHub
    github_patterns = [
        r'github\.com/([^\s/]+/[^\s/]+)',
        r'github\.com/([^\s/]+)/([^\s/]+)/',
    ]
    for pattern in github_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            repo = match.group(1) if len(match.groups()) == 1 else f"{match.group(1)}/{match.group(2)}"
            item["original_source"] = f"https://github.com/{repo}"
            item["source_type"] = "GitHub 仓库"
            item["is_second_hand"] = True
            return item

    # 3. 转载声明
    repost_keywords = ["转载", "本文来自", "来源：", "原文链接", "原发", "转自", "源自"]
    for kw in repost_keywords:
        if kw in content[:500]:
            url_match = re.search(r'(?:原文链接|来源|转自)[：:]\s*(https?://[^\s]+)', content[:1000])
            if url_match:
                item["original_source"] = url_match.group(1)
                item["source_type"] = "转载（已提取链接）"
            else:
                item["original_source"] = "待溯源（建议人工核查）"
                item["source_type"] = "疑似转载"
            item["is_second_hand"] = True
            return item

    # 4. 知乎专栏（当前来源）
    if "zhuanlan.zhihu.com" in url or "zhihu.com" in url:
        item["original_source"] = url
        item["source_type"] = "知乎专栏（当前来源）"
        external_match = re.search(r'(?:原文|参考|来源)[：:]\s*(https?://[^\s]+)', content[:500])
        if external_match:
            item["original_source"] = external_match.group(1)
            item["source_type"] = "转载（知乎专栏）"
            item["is_second_hand"] = True
        return item

    # 5. 个人博客/技术博客
    if url and ("blog" in url or "tech" in url or "medium.com" in url or "dev.to" in url):
        item["original_source"] = url
        item["source_type"] = "个人/技术博客"
        return item

    # 6. 其他 URL
    if url:
        item["original_source"] = url
        item["source_type"] = "当前页面来源"
        return item

    return item


def find_original_article(content: str) -> Optional[str]:
    match = re.search(r'arxiv\.org/abs/(\d+\.\d+)', content, re.IGNORECASE)
    if match:
        return f"https://arxiv.org/abs/{match.group(1)}"

    match = re.search(r'github\.com/([^\s/]+/[^\s/]+)', content, re.IGNORECASE)
    if match:
        return f"https://github.com/{match.group(1)}"

    url_match = re.search(r'https?://[^\s]+', content)
    if url_match:
        url = url_match.group(0)
        social_media = ["xiaohongshu", "zhihu", "weibo", "douyin", "tiktok", "instagram", "twitter"]
        if not any(sm in url.lower() for sm in social_media):
            return url

    return None
