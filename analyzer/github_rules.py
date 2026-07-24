"""GitHub 仓库筛选的第一层元数据与内容规则。"""

from __future__ import annotations

from typing import Dict, Iterable, List, Set, Tuple
from urllib.parse import urlparse

import config
from analyzer.github_common import append_github_filter_stage


def _raw(item: Dict) -> Dict:
    value = item.get("raw", {})
    return value if isinstance(value, dict) else {}


def _repository_id(item: Dict) -> str:
    raw = _raw(item)
    return str(raw.get("id") or raw.get("repository_id") or "").strip()


def _full_name(item: Dict) -> str:
    raw = _raw(item)
    return str(raw.get("full_name") or item.get("title") or "").strip()


def _valid_github_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return (
        parsed.scheme == "https"
        and parsed.netloc.casefold() in {"github.com", "www.github.com"}
        and len([part for part in parsed.path.split("/") if part]) >= 2
    )


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


def validate_github_rule_config() -> None:
    rules = getattr(config, "GITHUB_RULE_FILTER", None)
    if not isinstance(rules, dict):
        raise ValueError("GITHUB_RULE_FILTER 必须是字典")
    minimum = rules.get("min_content_chars")
    if not isinstance(minimum, int) or minimum < 1:
        raise ValueError("GITHUB_RULE_FILTER.min_content_chars 必须是正整数")
    for name in ("exclude_keywords",):
        values = rules.get(name, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) for value in values
        ):
            raise ValueError(f"GITHUB_RULE_FILTER.{name} 必须是字符串列表")
    for name in ("allow_forks", "allow_archived", "allow_disabled"):
        if not isinstance(rules.get(name), bool):
            raise ValueError(f"GITHUB_RULE_FILTER.{name} 必须是布尔值")


def evaluate_github_rules(
    item: Dict,
    seen_ids: Set[str],
    seen_names: Set[str],
) -> Dict[str, object]:
    """评估仓库基本有效性，不调用外部服务。"""
    rules = config.GITHUB_RULE_FILTER
    raw = _raw(item)
    repository_id = _repository_id(item)
    full_name = _full_name(item)
    source = str(item.get("source", "") or "").casefold()

    if source != "github":
        return _result("drop", "GITHUB_RULE_WRONG_PLATFORM")
    if not repository_id:
        return _result("drop", "GITHUB_RULE_MISSING_ID")
    if not full_name or "/" not in full_name:
        return _result("drop", "GITHUB_RULE_INVALID_FULL_NAME")
    if not _valid_github_url(item.get("url")):
        return _result("drop", "GITHUB_RULE_INVALID_REPOSITORY_URL")
    if raw.get("archived") and not rules["allow_archived"]:
        return _result("drop", "GITHUB_RULE_ARCHIVED")
    if raw.get("disabled") and not rules["allow_disabled"]:
        return _result("drop", "GITHUB_RULE_DISABLED")
    if raw.get("fork") and not rules["allow_forks"]:
        return _result("drop", "GITHUB_RULE_FORK_NOT_ALLOWED")

    searchable = " ".join(
        [
            full_name,
            str(raw.get("description") or ""),
            str(raw.get("readme") or item.get("content") or ""),
        ]
    ).casefold()
    for keyword in rules.get("exclude_keywords", []):
        normalized = keyword.strip().casefold()
        if normalized and normalized in searchable:
            return _result(
                "drop",
                "GITHUB_RULE_EXCLUDED_KEYWORD",
                {"keyword": keyword},
            )

    meaningful_chars = len("".join(searchable.split()))
    minimum = int(rules["min_content_chars"])
    if meaningful_chars < minimum:
        return _result(
            "drop",
            "GITHUB_RULE_CONTENT_TOO_SHORT",
            {"meaningful_chars": meaningful_chars, "minimum": minimum},
        )

    normalized_name = full_name.casefold()
    if repository_id in seen_ids:
        return _result("drop", "GITHUB_RULE_DUPLICATE_ID")
    if normalized_name in seen_names:
        return _result("drop", "GITHUB_RULE_DUPLICATE_FULL_NAME")
    seen_ids.add(repository_id)
    seen_names.add(normalized_name)
    return _result(
        "pass",
        "GITHUB_RULES_PASSED",
        {
            "repository_id": repository_id,
            "full_name": full_name,
            "meaningful_chars": meaningful_chars,
        },
    )


def apply_github_rules(
    items: Iterable[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """批量执行 GitHub 第一层规则。"""
    validate_github_rule_config()
    passed: List[Dict] = []
    dropped: List[Dict] = []
    seen_ids: Set[str] = set()
    seen_names: Set[str] = set()
    for item in items:
        result = evaluate_github_rules(item, seen_ids, seen_names)
        append_github_filter_stage(item, result)
        (passed if result["decision"] == "pass" else dropped).append(item)
    return passed, dropped
