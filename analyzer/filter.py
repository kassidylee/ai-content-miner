# analyzer/filter.py
import re
import config


def rule_filter(article: Dict) -> tuple:
    """规则过滤：字数、关键词、链接检测"""
    content = article.get("content", "")
    title = article.get("title", "")

    # 字数过滤
    if len(content) < config.MIN_CONTENT_LENGTH:
        return False, f"内容过短（{len(content)}字 < {config.MIN_CONTENT_LENGTH}）"

    # 低质量关键词
    for kw in config.LOW_QUALITY_KEYWORDS:
        if kw in title or kw in content[:200]:
            return False, f"含低质量关键词 '{kw}'"

    # 链接检测（完全无链接的内容降权，但不直接过滤）
    has_link = "http" in content or "arXiv" in content or "github.com" in content
    if not has_link:
        # 标记为低可信，但不直接过滤
        article["_low_credibility"] = True

    return True, "通过"


def get_blogger_weight(article: Dict) -> float:
    """获取博主权重（白名单 + lingzao 分析）"""
    author = article.get("author", "")
    source = article.get("source", "")

    # 从白名单匹配
    for name, info in config.BLOGGER_WHITELIST.items():
        if name in author or author in name:
            return info.get("weight", 1.0)

    # 从 lingzao 分析中获取
    lingzao = article.get("lingzao_analysis", {})
    quality = lingzao.get("quality_score", 5.0)
    # 将质量分映射为权重：5分→1.0，10分→1.5
    weight = 0.5 + quality / 10.0
    return min(1.5, weight)