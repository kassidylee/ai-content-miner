# analyzer/filter.py
"""
规则过滤模块（小红书和知乎专用）
 
包含：
  1. 旧版 rule_filter（兼容保留，供其他模块调用）
  2. 旧版 get_blogger_weight（已移除 lingzao 依赖，小红书/知乎不使用白名单）
  3. 新版四层筛选（multi_stage_filter、rule_filter_enhanced、comment_analysis、author_profile_analysis）
"""
import re
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

import config


# ============================================================
# 配置常量（可在 config.py 中覆盖）
# ============================================================

AUTHOR_PROFILE_THRESHOLD = getattr(config, 'AUTHOR_PROFILE_THRESHOLD', 0.9)
COMMENT_PASS_THRESHOLD = getattr(config, 'COMMENT_PASS_THRESHOLD', 0.5)
SEMANTIC_DEDUP_THRESHOLD = getattr(config, 'SEMANTIC_DEDUP_THRESHOLD', 0.85)

RULE_SCORE_MIN = 0.5
RULE_SCORE_MAX = 1.3
COMMENT_SCORE_MIN = 0.5
COMMENT_SCORE_MAX = 1.3
AUTHOR_SCORE_MIN = 0.7
AUTHOR_SCORE_MAX = 1.4


# ============================================================
# 旧版接口（兼容保留）
# ============================================================

def rule_filter(article: Dict) -> Tuple[bool, str]:
    """
    旧版规则过滤（兼容保留，供其他模块调用）
    小红书和知乎仍使用此函数进行基础过滤
    """
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
    """
    获取博主权重（小红书和知乎专用，不使用白名单）
    已移除 lingzao 依赖，直接返回 1.0
    """
    # 小红书和知乎不使用博主白名单，统一返回 1.0
    return 1.0


# ============================================================
# 新版四层筛选（供小红书和知乎使用）
# ============================================================

class FilterLevel(Enum):
    RULE = "rule"
    SEMANTIC = "semantic"
    COMMENT = "comment"
    AUTHOR = "author"


@dataclass
class FilterResult:
    passed: bool = True
    rule_passed: bool = True
    semantic_passed: bool = True
    comment_passed: bool = True
    author_passed: bool = True

    rule_reason: str = ""
    semantic_reason: str = ""
    comment_reason: str = ""
    author_reason: str = ""

    rule_score: float = 1.0
    semantic_score: float = 1.0
    comment_score: float = 1.0
    author_score: float = 1.0

    flags: List[str] = field(default_factory=list)
    _low_credibility: bool = False

    def total_score(self) -> float:
        return (self.rule_score * self.semantic_score *
                self.comment_score * self.author_score)

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "rule_passed": self.rule_passed,
            "semantic_passed": self.semantic_passed,
            "comment_passed": self.comment_passed,
            "author_passed": self.author_passed,
            "rule_reason": self.rule_reason,
            "semantic_reason": self.semantic_reason,
            "comment_reason": self.comment_reason,
            "author_reason": self.author_reason,
            "rule_score": self.rule_score,
            "semantic_score": self.semantic_score,
            "comment_score": self.comment_score,
            "author_score": self.author_score,
            "total_score": self.total_score(),
            "flags": self.flags,
            "low_credibility": self._low_credibility
        }


def detect_quality_signals(content: str, title: str) -> Dict[str, Any]:
    """检测内容中的优质信号"""
    signals = {
        "has_code": False,
        "has_structured": False,
        "has_deep_keywords": False,
        "signal_count": 0,
        "content_type": "unknown"
    }

    if "```" in content or "```python" in content or "```javascript" in content:
        signals["has_code"] = True
        signals["signal_count"] += 1

    structured_patterns = [
        r'\n[-*]\s+',
        r'\n\d+\.\s+',
        r'\|.*\|.*\|',
        r'\n>\s+',
    ]
    for pattern in structured_patterns:
        if re.search(pattern, content[:1000]):
            signals["has_structured"] = True
            signals["signal_count"] += 1
            break

    deep_keywords = [
        "我认为", "我的观点", "反思", "为什么", "本质",
        "核心", "关键", "值得思考", "值得注意", "重要",
        "framework", "methodology", "insight", "perspective",
        "paradigm", "architecture", "mechanism",
        "分析", "解读", "拆解", "深度", "系统"
    ]
    for kw in deep_keywords:
        if kw in content[:500] or kw in title:
            signals["has_deep_keywords"] = True
            signals["signal_count"] += 1
            break

    if signals["has_code"] and signals["has_structured"]:
        signals["content_type"] = "technical_tutorial"
    elif signals["has_code"]:
        signals["content_type"] = "code_share"
    elif signals["has_deep_keywords"] and len(content) > 200:
        signals["content_type"] = "deep_insight"
    elif signals["has_structured"] and len(content) > 100:
        signals["content_type"] = "structured_info"
    elif len(content) < 200 and signals["has_deep_keywords"]:
        signals["content_type"] = "short_insight"
    elif len(content) < 100:
        signals["content_type"] = "short_content"
    else:
        signals["content_type"] = "general"

    return signals


def _calculate_word_penalty(word_count: int, signal_count: int) -> float:
    """根据字数和优质信号数量计算惩罚系数"""
    if word_count < 100:
        if signal_count >= 2:
            return 0.85
        elif signal_count >= 1:
            return 0.75
        else:
            return 0.60
    elif word_count < 300:
        return 0.95 if signal_count >= 2 else 0.85
    elif word_count < 500:
        return 0.95
    else:
        return 1.0


def rule_filter_enhanced(article: Dict) -> FilterResult:
    """增强版规则过滤（第一层）"""
    result = FilterResult()
    content = article.get("content", "")
    title = article.get("title", "")
    word_count = len(content)

    # 硬性淘汰：低质量关键词
    for kw in getattr(config, 'LOW_QUALITY_KEYWORDS', []):
        if kw in title or kw in content[:200]:
            result.rule_passed = False
            result.passed = False
            result.rule_reason = f"含低质量关键词 '{kw}'"
            result.rule_score = 0.0
            result.flags.append("low_quality_keyword")
            return result

    # 检测优质信号
    signals = detect_quality_signals(content, title)
    result.flags.append(f"content_type:{signals['content_type']}")
    result.flags.append(f"signals:{signals['signal_count']}")

    # 计算评分
    word_penalty = _calculate_word_penalty(word_count, signals["signal_count"])
    signal_bonus = 1.0 + (signals["signal_count"] * 0.05)

    has_link = ("http" in content or "arXiv" in content or "github.com" in content)
    link_bonus = 1.05 if has_link else 0.95
    result._low_credibility = not has_link

    title_bonus = 1.0
    if len(title) < 5:
        title_bonus = 0.95
    elif len(title) > 15:
        title_bonus = 1.02

    result.rule_score = 1.0 * word_penalty * signal_bonus * link_bonus * title_bonus
    result.rule_score = max(RULE_SCORE_MIN, min(RULE_SCORE_MAX, result.rule_score))

    # 生成原因
    reasons = []
    if word_count < 100:
        reasons.append(f"超短文({word_count}字)")
    elif word_count < 300:
        reasons.append(f"短文({word_count}字)")

    if signals["signal_count"] >= 2:
        reasons.append("含多个优质信号")
    elif signals["signal_count"] >= 1:
        reasons.append("含优质信号")

    if has_link:
        reasons.append("含外部链接")

    result.rule_reason = "规则层: " + " | ".join(reasons)

    if word_count < 100:
        result.flags.append("very_short")
    if word_count < 300:
        result.flags.append("short")
    if signals["has_code"]:
        result.flags.append("has_code")
    if signals["has_deep_keywords"]:
        result.flags.append("has_deep_insight")

    return result


def semantic_dedup(
    articles: List[Dict],
    threshold: float = SEMANTIC_DEDUP_THRESHOLD,
    text_field: str = "title"
) -> Tuple[List[Dict], Dict[str, Any]]:
    """基于语义相似度去重"""
    if len(articles) <= 1:
        return articles, {
            "total": len(articles),
            "kept": len(articles),
            "removed": 0,
            "duplicate_groups": 0
        }

    try:
        from utils.embedding import encode, cosine_similarity
    except ImportError:
        return articles, {
            "total": len(articles),
            "kept": len(articles),
            "removed": 0,
            "duplicate_groups": 0,
            "error": "embedding module not available"
        }

    texts = [art.get(text_field, "") + " " + (art.get("content", "")[:200]) for art in articles]
    vectors = encode(texts)

    keep_indices = []
    duplicate_groups = 0
    seen = set()

    for i in range(len(articles)):
        if i in seen:
            continue

        keep_indices.append(i)
        group = [i]

        for j in range(i + 1, len(articles)):
            if j in seen:
                continue
            sim = cosine_similarity(vectors[i], vectors[j])
            if sim >= threshold:
                seen.add(j)
                group.append(j)

        if len(group) > 1:
            duplicate_groups += 1

    kept_articles = [articles[i] for i in keep_indices]

    for i, idx in enumerate(keep_indices):
        kept_articles[i]["_dedup_group_id"] = i
        kept_articles[i]["_dedup_kept"] = True

    return kept_articles, {
        "total": len(articles),
        "kept": len(kept_articles),
        "removed": len(articles) - len(kept_articles),
        "duplicate_groups": duplicate_groups
    }


def semantic_filter(
    article: Dict,
    existing_articles: List[Dict],
    threshold: float = SEMANTIC_DEDUP_THRESHOLD
) -> FilterResult:
    """对单篇文章进行语义相似度过滤"""
    result = FilterResult()

    if not existing_articles:
        result.semantic_reason = "无历史文章，通过"
        return result

    try:
        from utils.embedding import encode, cosine_similarity
    except ImportError:
        result.semantic_reason = "embedding 模块不可用，跳过"
        return result

    query_text = article.get("title", "") + " " + (article.get("content", "")[:200])
    existing_texts = [art.get("title", "") + " " + (art.get("content", "")[:200]) for art in existing_articles]

    query_vec = encode([query_text])[0]
    existing_vecs = encode(existing_texts)

    max_sim = 0.0
    for vec in existing_vecs:
        sim = cosine_similarity(query_vec, vec)
        if sim > max_sim:
            max_sim = sim

    if max_sim >= threshold:
        result.semantic_passed = False
        result.passed = False
        result.semantic_reason = f"与已有文章高度相似（相似度 {max_sim:.3f} ≥ {threshold}）"
        result.semantic_score = 0.0
        result.flags.append("semantic_duplicate")
    else:
        result.semantic_reason = f"语义去重通过（最高相似度 {max_sim:.3f} < {threshold}）"
        result.semantic_score = min(1.0, 1.0 - max_sim * 0.2)

    return result


def comment_analysis(article: Dict) -> FilterResult:
    """评论区分析（基于互动指标）"""
    result = FilterResult()

    likes = int(article.get("likes", 0) or 0)
    comments = int(article.get("comments", 0) or 0)
    collects = int(article.get("collects", 0) or 0)
    shares = int(article.get("shares", 0) or 0)

    if comments == 0:
        comment_score = 0.5
        result.flags.append("no_comments")
    elif comments < 3:
        comment_score = 0.7
    elif comments < 10:
        comment_score = 0.9
    elif comments < 50:
        comment_score = 1.0
    else:
        comment_score = min(1.2, 1.0 + (comments - 50) / 500)

    if likes == 0:
        like_score = 0.5
        result.flags.append("no_likes")
    elif likes < 10:
        like_score = 0.8
    elif likes < 50:
        like_score = 1.0
    elif likes < 200:
        like_score = 1.1
    else:
        like_score = min(1.3, 1.0 + (likes - 200) / 1000)

    if collects == 0:
        collect_score = 0.8
    elif collects < 5:
        collect_score = 0.9
    elif collects < 20:
        collect_score = 1.0
    elif collects < 100:
        collect_score = 1.1
    else:
        collect_score = min(1.3, 1.0 + (collects - 100) / 500)

    if likes > 0 and comments > 0:
        ratio = comments / likes
        if 0.1 < ratio < 0.5:
            ratio_score = 1.1
        elif ratio > 1.0:
            ratio_score = 1.05
        else:
            ratio_score = 0.9
    else:
        ratio_score = 1.0

    if shares == 0:
        share_score = 0.9
    elif shares < 10:
        share_score = 1.0
    else:
        share_score = min(1.15, 1.0 + (shares - 10) / 200)

    result.comment_score = (
        comment_score * 0.25 +
        like_score * 0.25 +
        collect_score * 0.20 +
        ratio_score * 0.15 +
        share_score * 0.15
    )
    result.comment_score = max(COMMENT_SCORE_MIN, min(COMMENT_SCORE_MAX, result.comment_score))

    if comments > 20 and likes < 5:
        result.comment_score *= 0.8
        result.flags.append("suspicious_interaction")

    if collects > 20 and collects > likes * 0.5:
        result.comment_score *= 1.05
        result.flags.append("high_value_content")

    result.comment_reason = f"互动: 评论{comments} 点赞{likes} 收藏{collects}"

    if result.comment_score < COMMENT_PASS_THRESHOLD:
        result.comment_passed = False
        result.passed = False
        result.comment_reason += "（互动质量过低）"

    return result


def author_profile_analysis(article: Dict) -> FilterResult:
    """博主画像分析（基于作者维度）"""
    result = FilterResult()

    followers = int(article.get("followers", 0) or 0)
    total_likes = int(article.get("author_total_likes", 0) or 0)
    total_notes = int(article.get("author_total_notes", 0) or 0)
    verified = article.get("verified", False) or False
    author_following = int(article.get("author_following", 0) or 0)

    data_missing = (followers == 0 and total_likes == 0 and total_notes == 0)
    if data_missing:
        result.author_score = 1.0
        result.author_reason = "博主数据缺失，给予默认评分"
        result.flags.append("author_data_missing")
        return result

    # 粉丝数评分
    if followers >= 100000:
        followers_score = 1.3
        result.flags.append("top_creator")
    elif followers >= 10000:
        followers_score = 1.2
        result.flags.append("mid_creator")
    elif followers >= 1000:
        followers_score = 1.1
        result.flags.append("small_creator")
    elif followers >= 100:
        followers_score = 1.0
    else:
        followers_score = 0.85
        result.flags.append("new_creator")

    verified_score = 1.05 if verified else 1.0
    if verified:
        result.flags.append("verified")

    if total_notes >= 100:
        notes_score = 1.05
        result.flags.append("high_activity")
    elif total_notes >= 30:
        notes_score = 1.02
    elif total_notes >= 10:
        notes_score = 1.0
    else:
        notes_score = 0.95
        result.flags.append("low_activity")

    if followers > 0:
        engagement_rate = total_likes / followers
        if engagement_rate >= 5:
            engagement_score = 1.1
            result.flags.append("high_engagement")
        elif engagement_rate >= 1:
            engagement_score = 1.05
        else:
            engagement_score = 0.95
    else:
        engagement_score = 1.0

    if followers > 0 and author_following > 0:
        follow_ratio = author_following / followers
        if follow_ratio < 0.5:
            ratio_score = 1.02
        elif follow_ratio > 2:
            ratio_score = 0.95
        else:
            ratio_score = 1.0
    else:
        ratio_score = 1.0

    result.author_score = (
        followers_score * 0.35 +
        verified_score * 0.15 +
        notes_score * 0.15 +
        engagement_score * 0.25 +
        ratio_score * 0.10
    )
    result.author_score = max(AUTHOR_SCORE_MIN, min(AUTHOR_SCORE_MAX, result.author_score))

    reasons = []
    if followers >= 10000:
        reasons.append(f"粉丝 {followers/10000:.1f}w")
    elif followers >= 1000:
        reasons.append(f"粉丝 {followers}")
    elif followers > 0:
        reasons.append("新博主")
    else:
        reasons.append("未知")

    if verified:
        reasons.append("认证")
    if total_notes >= 100:
        reasons.append("活跃")

    result.author_reason = "博主画像: " + " | ".join(reasons)

    threshold = getattr(config, 'AUTHOR_PROFILE_THRESHOLD', 0.9)
    if result.author_score < threshold:
        result.author_passed = False
        result.passed = False
        result.author_reason += f"（得分 {result.author_score:.2f} < 阈值 {threshold}）"

    return result


def multi_stage_filter(
    article: Dict,
    existing_articles: List[Dict] = None,
    enable_semantic: bool = True,
    enable_comment: bool = True,
    enable_author_profile: bool = True
) -> FilterResult:
    """四步综合筛选入口（小红书和知乎专用）"""
    # 第一层：规则过滤
    rule_result = rule_filter_enhanced(article)
    if not rule_result.rule_passed:
        return rule_result

    # 第二层：语义去重
    semantic_result = FilterResult()
    if enable_semantic and existing_articles:
        semantic_result = semantic_filter(article, existing_articles)
        if not semantic_result.semantic_passed:
            return semantic_result
    else:
        semantic_result.semantic_reason = "语义去重已跳过或未启用"

    # 第三层：评论区分析
    comment_result = FilterResult()
    if enable_comment:
        comment_result = comment_analysis(article)
        if not comment_result.comment_passed:
            return comment_result
    else:
        comment_result.comment_reason = "评论分析已跳过"

    # 第四层：博主画像
    author_result = FilterResult()
    if enable_author_profile:
        author_result = author_profile_analysis(article)
        if not author_result.author_passed:
            return author_result
    else:
        author_result.author_reason = "博主画像已跳过"
        author_result.author_score = 1.0

    # 合并结果
    combined = FilterResult()
    combined.rule_passed = rule_result.rule_passed
    combined.rule_score = rule_result.rule_score
    combined.rule_reason = rule_result.rule_reason

    combined.semantic_passed = semantic_result.semantic_passed
    combined.semantic_score = semantic_result.semantic_score
    combined.semantic_reason = semantic_result.semantic_reason

    combined.comment_passed = comment_result.comment_passed
    combined.comment_score = comment_result.comment_score
    combined.comment_reason = comment_result.comment_reason

    combined.author_passed = author_result.author_passed
    combined.author_score = author_result.author_score
    combined.author_reason = author_result.author_reason

    combined.flags = (rule_result.flags + semantic_result.flags +
                      comment_result.flags + author_result.flags)
    combined._low_credibility = rule_result._low_credibility

    combined.passed = True
    return combined


def batch_filter(
    articles: List[Dict],
    enable_semantic: bool = True,
    enable_comment: bool = True,
    enable_author_profile: bool = True,
    semantic_threshold: float = SEMANTIC_DEDUP_THRESHOLD
) -> Tuple[List[Dict], Dict]:
    """批量四步筛选"""
    stats = {
        "total": len(articles),
        "rule_passed": 0,
        "semantic_removed": 0,
        "comment_passed": 0,
        "author_passed": 0,
        "final_passed": 0
    }

    rule_passed = []
    for art in articles:
        result = rule_filter_enhanced(art)
        if result.rule_passed:
            rule_passed.append(art)
            stats["rule_passed"] += 1

    semantic_passed, dedup_stats = semantic_dedup(
        rule_passed,
        threshold=semantic_threshold
    )
    stats["semantic_removed"] = dedup_stats.get("removed", 0)

    comment_passed = []
    for art in semantic_passed:
        result = comment_analysis(art)
        if result.comment_passed:
            comment_passed.append(art)
            stats["comment_passed"] += 1

    final_passed = []
    for art in comment_passed:
        result = author_profile_analysis(art)
        if result.author_passed:
            final_passed.append(art)
            stats["author_passed"] += 1

    stats["final_passed"] = len(final_passed)
    return final_passed, stats