# analyzer/filter.py
"""
规则过滤模块
1. 字数过滤
2. 低质量关键词过滤
3. 链接检测（标记低可信）
4. 博主权重计算
"""
import re
from typing import Dict, Tuple

import config


def rule_filter(article: Dict) -> Tuple[bool, str]:
    content = article.get("content", "")
    title = article.get("title", "")

    if len(content) < config.MIN_CONTENT_LENGTH:
        return False, f"内容过短（{len(content)}字 < {config.MIN_CONTENT_LENGTH}）"

    for kw in config.LOW_QUALITY_KEYWORDS:
        if kw in title or kw in content[:200]:
            return False, f"含低质量关键词 '{kw}'"

    has_link = ("http" in content or "arXiv" in content or "github.com" in content or "arxiv.org" in content)
    article["_low_credibility"] = not has_link

    return True, "通过"


def get_blogger_weight(article: Dict) -> float:
    author = article.get("author", "")
    source = article.get("source", "")

    if not author or author == "":
        return 1.0

    from utils.parser import source_classify
    platform = source_classify(source)

    for name, info in config.BLOGGER_WHITELIST.items():
        white_platform = info.get("source", platform)
        if name == author and white_platform == platform:
            return info.get("weight", 1.0)
        if "source" not in info and name == author:
            return info.get("weight", 1.0)
        if white_platform == platform and (name in author or author in name):
            if len(name) >= 2:
                return info.get("weight", 1.0)

    lingzao = article.get("lingzao_analysis", {})
    quality = lingzao.get("quality_score", 5.0)
    weight = 0.5 + quality / 10.0
    return min(1.5, max(0.8, weight))