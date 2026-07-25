"""Twitter 新流程的第一层规则筛选。"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Set, Tuple
from urllib.parse import urlparse

import config
from analyzer.twitter_common import append_twitter_filter_stage


URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"(?<!\w)@\w+")
DECORATION_PATTERN = re.compile(r"[^\w\u4e00-\u9fff#]+", re.UNICODE)


def meaningful_twitter_text(item: Dict) -> str:
    """移除链接、用户名和装饰字符，保留有效正文。"""
    content = str(item.get("content", "") or "")
    content = URL_PATTERN.sub(" ", content)
    content = MENTION_PATTERN.sub(" ", content)
    content = DECORATION_PATTERN.sub(" ", content)
    return re.sub(r"\s+", " ", content).strip()


def _valid_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _first_external_url(item: Dict) -> str:
    for entry in item.get("referenced_urls", []):
        if isinstance(entry, dict) and _valid_http_url(entry.get("url")):
            return str(entry["url"]).strip().casefold()
    return ""


def _topic_searchable_text(item: Dict) -> str:
    """合并可证明主题相关性的正文信息，不采信 X 返回的搜索命中标签。"""
    parts = [
        str(item.get("title", "") or ""),
        str(item.get("content", "") or ""),
        str(item.get("quoted_content", "") or ""),
    ]
    metadata = item.get("platform_metadata", {})
    if isinstance(metadata, dict):
        hashtags = metadata.get("hashtags", [])
        if isinstance(hashtags, list):
            parts.extend(str(tag) for tag in hashtags)
    for entry in item.get("referenced_urls", []):
        if isinstance(entry, dict):
            # 链接展示文字可能包含项目或论文名；原始 URL 不参与主题命中。
            parts.append(str(entry.get("label", "") or ""))
    return re.sub(r"\s+", " ", " ".join(parts)).casefold()


def _contains_topic_keyword(searchable: str, keyword: str) -> bool:
    """中文使用连续子串，英文使用单词边界，避免 LLM 命中更长单词。"""
    normalized = re.sub(r"\s+", " ", keyword.strip()).casefold()
    if not normalized:
        return False
    if not normalized.isascii():
        return normalized in searchable
    pattern = re.escape(normalized).replace(r"\ ", r"\s+")
    return re.search(
        rf"(?<![a-z0-9]){pattern}(?![a-z0-9])",
        searchable,
    ) is not None


def _metric(item: Dict, name: str) -> int:
    """把缺失或异常互动指标归零，防止脏数据绕过质量门槛。"""
    metrics = item.get("metrics", {})
    if not isinstance(metrics, dict):
        return 0
    value = metrics.get(name, 0)
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _matched_keywords(searchable: str, keywords: Iterable[str]) -> List[str]:
    return [
        str(keyword)
        for keyword in keywords
        if _contains_topic_keyword(searchable, str(keyword))
    ]


def _evidence_domains(item: Dict, configured: Iterable[str]) -> List[str]:
    """返回帖子实际引用的一手技术域名，子域名也视为有效证据。"""
    allowed = {
        str(domain).strip().casefold().removeprefix("www.")
        for domain in configured
        if str(domain).strip()
    }
    matched: Set[str] = set()
    for entry in item.get("referenced_urls", []):
        if not isinstance(entry, dict):
            continue
        domain = str(entry.get("domain", "") or "").strip().casefold()
        if not domain:
            domain = urlparse(
                str(entry.get("url", "") or "")
            ).netloc.casefold()
        domain = domain.removeprefix("www.")
        for expected in allowed:
            if domain == expected or domain.endswith(f".{expected}"):
                matched.add(expected)
    return sorted(matched)


def _result(
    decision: str,
    reason_code: str,
    details: Dict[str, object] | None = None,
) -> Dict[str, object]:
    return {
        "stage": "rules",
        "decision": decision,
        "reason_codes": [reason_code],
        "details": details or {},
    }


def validate_twitter_rule_config() -> None:
    """在发起网络请求前发现配置类型、空列表和非法阈值。"""
    rules = config.TWITTER_RULE_FILTER
    if not isinstance(rules, dict):
        raise ValueError("TWITTER_RULE_FILTER 必须是字典")
    minimum = rules.get("min_meaningful_chars")
    if not isinstance(minimum, int) or minimum < 1:
        raise ValueError(
            "TWITTER_RULE_FILTER.min_meaningful_chars 必须是正整数"
        )
    for name in (
        "min_view_count",
        "min_social_engagement",
        "min_technical_score",
    ):
        value = rules.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"TWITTER_RULE_FILTER.{name} 必须是非负整数"
            )
    for name in (
        "allowed_languages",
        "required_topic_keywords",
        "technical_keywords",
        "technical_depth_keywords",
        "business_penalty_keywords",
        "promotion_penalty_keywords",
        "evidence_domains",
        "exclude_keywords",
    ):
        values = rules.get(name, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip()
            for value in values
        ):
            raise ValueError(f"TWITTER_RULE_FILTER.{name} 必须是字符串列表")
    if not rules.get("required_topic_keywords"):
        raise ValueError(
            "TWITTER_RULE_FILTER.required_topic_keywords 不能为空"
        )
    if not rules.get("technical_keywords"):
        raise ValueError(
            "TWITTER_RULE_FILTER.technical_keywords 不能为空"
        )
    if not rules.get("technical_depth_keywords"):
        raise ValueError(
            "TWITTER_RULE_FILTER.technical_depth_keywords 不能为空"
        )


def evaluate_twitter_rules(
    item: Dict,
    seen_texts: Set[str],
    seen_urls: Set[str],
) -> Dict[str, object]:
    """评估单条 Twitter 内容，不调用外部服务。"""
    rules = config.TWITTER_RULE_FILTER
    metadata = item.get("platform_metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    # 第一组是数据完整性和帖子类型检查，失败后无需继续文本分析。
    if item.get("platform") != "x":
        return _result("drop", "TWITTER_RULE_WRONG_PLATFORM")
    if not item.get("platform_item_id"):
        return _result("drop", "TWITTER_RULE_MISSING_ID")
    if not str(item.get("content", "") or "").strip():
        return _result("drop", "TWITTER_RULE_EMPTY_CONTENT")
    if not _valid_http_url(item.get("source_url")):
        return _result("drop", "TWITTER_RULE_INVALID_SOURCE_URL")
    if item.get("published_at") is None:
        return _result("drop", "TWITTER_RULE_MISSING_PUBLISHED_AT")
    if rules.get("drop_sensitive") and metadata.get("possibly_sensitive"):
        return _result("drop", "TWITTER_RULE_SENSITIVE_CONTENT")
    if not rules.get("allow_replies", True) and metadata.get("is_reply"):
        return _result("drop", "TWITTER_RULE_REPLY_NOT_ALLOWED")
    if not rules.get("allow_retweets", True) and metadata.get("is_retweet"):
        return _result("drop", "TWITTER_RULE_RETWEET_NOT_ALLOWED")
    if not rules.get("allow_quotes", True) and metadata.get("is_quote"):
        return _result("drop", "TWITTER_RULE_QUOTE_NOT_ALLOWED")

    # 语言和硬排除词属于低成本检查，放在主题及评分计算之前。
    language = str(metadata.get("lang", "") or "").casefold()
    allowed = {
        str(value).casefold()
        for value in rules.get("allowed_languages", [])
    }
    if allowed and language and language not in allowed:
        return _result(
            "drop",
            "TWITTER_RULE_LANGUAGE_NOT_ALLOWED",
            {"language": language},
        )

    searchable = _topic_searchable_text(item)
    for keyword in rules.get("exclude_keywords", []):
        normalized = str(keyword).strip().casefold()
        if normalized and normalized in searchable:
            return _result(
                "drop",
                "TWITTER_RULE_EXCLUDED_KEYWORD",
                {"keyword": str(keyword)},
            )

    # 搜索结果只代表 X 返回了该帖子；这里必须再次验证实际正文主题。
    matched_topics = _matched_keywords(
        searchable,
        rules.get("required_topic_keywords", []),
    )
    if not matched_topics:
        return _result(
            "drop",
            "TWITTER_RULE_TOPIC_NOT_RELEVANT",
        )

    # 外部链接可能承载主要证据，因此带链接的短帖允许继续进入证据检查。
    meaningful = meaningful_twitter_text(item)
    minimum = int(rules.get("min_meaningful_chars", 1) or 1)
    if len(meaningful) < minimum and not item.get("referenced_urls"):
        return _result(
            "drop",
            "TWITTER_RULE_CONTENT_TOO_SHORT",
            {"meaningful_chars": len(meaningful), "minimum": minimum},
        )

    # 技术评分把“谈论 AI”与“提供技术信息”分开，所有命中项都会写入审计数据。
    technical_hits = _matched_keywords(
        searchable,
        rules.get("technical_keywords", []),
    )
    technical_depth_hits = _matched_keywords(
        searchable,
        rules.get("technical_depth_keywords", []),
    )
    evidence_domains = _evidence_domains(
        item,
        rules.get("evidence_domains", []),
    )
    if not technical_hits and not evidence_domains:
        return _result(
            "drop",
            "TWITTER_RULE_TECHNICAL_SIGNAL_MISSING",
            {"matched_topic_keywords": matched_topics},
        )

    business_hits = _matched_keywords(
        searchable,
        rules.get("business_penalty_keywords", []),
    )
    promotion_hits = _matched_keywords(
        searchable,
        rules.get("promotion_penalty_keywords", []),
    )
    # 评分只按“是否命中某类信号”计一次，避免堆砌同类关键词刷高分。
    technical_score = 0
    if technical_hits:
        technical_score += 2
    if technical_depth_hits:
        technical_score += 1
    if evidence_domains:
        technical_score += 3
    if business_hits:
        technical_score -= 3
    if promotion_hits:
        technical_score -= 2
    min_technical_score = int(
        rules.get("min_technical_score", 0) or 0
    )
    technical_details = {
        "technical_score": technical_score,
        "min_technical_score": min_technical_score,
        "technical_keywords": technical_hits,
        "technical_depth_keywords": technical_depth_hits,
        "evidence_domains": evidence_domains,
        "business_penalties": business_hits,
        "promotion_penalties": promotion_hits,
    }
    if technical_score < min_technical_score:
        return _result(
            "drop",
            "TWITTER_RULE_TECHNICAL_SCORE_TOO_LOW",
            technical_details,
        )

    # 浏览量和社交互动满足任一门槛即可，兼顾高曝光内容和小众技术讨论。
    view_count = _metric(item, "view_count")
    social_engagement = sum(
        _metric(item, name)
        for name in (
            "like_count",
            "reply_count",
            "share_count",
            "quote_count",
            "bookmark_count",
        )
    )
    min_view_count = int(rules.get("min_view_count", 0) or 0)
    min_social_engagement = int(
        rules.get("min_social_engagement", 0) or 0
    )
    if (
        view_count < min_view_count
        and social_engagement < min_social_engagement
    ):
        return _result(
            "drop",
            "TWITTER_RULE_LOW_ENGAGEMENT",
            {
                "view_count": view_count,
                "social_engagement": social_engagement,
                "min_view_count": min_view_count,
                "min_social_engagement": min_social_engagement,
            },
        )

    # 去重放在最后，避免被前面已经淘汰的低质量帖子占用正文或链接键。
    text_key = meaningful.casefold()
    if text_key and text_key in seen_texts:
        return _result("drop", "TWITTER_RULE_DUPLICATE_CONTENT")
    external_url = _first_external_url(item)
    if external_url and external_url in seen_urls:
        return _result("drop", "TWITTER_RULE_DUPLICATE_EXTERNAL_URL")

    if text_key:
        seen_texts.add(text_key)
    if external_url:
        seen_urls.add(external_url)
    return _result(
        "pass",
        "TWITTER_RULES_PASSED",
        {
            "language": language,
            "meaningful_chars": len(meaningful),
            "matched_topic_keywords": matched_topics,
            "view_count": view_count,
            "social_engagement": social_engagement,
            **technical_details,
        },
    )


def apply_twitter_rules(
    items: Iterable[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """批量执行 Twitter 第一层筛选。"""
    passed: List[Dict] = []
    dropped: List[Dict] = []
    seen_texts: Set[str] = set()
    seen_urls: Set[str] = set()
    for item in items:
        result = evaluate_twitter_rules(item, seen_texts, seen_urls)
        append_twitter_filter_stage(item, result)
        (passed if result["decision"] == "pass" else dropped).append(item)
    return passed, dropped
