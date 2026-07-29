"""Reddit 专用筛选链路的共享审计工具。"""

from __future__ import annotations

from typing import Dict


def raw_reddit_record(item: Dict) -> Dict:
    """返回标准化文章中保留的 Reddit 原始记录。"""
    value = item.get("raw", {})
    return value if isinstance(value, dict) else {}


def append_reddit_filter_stage(
    item: Dict,
    stage_result: Dict[str, object],
) -> None:
    """追加阶段结果，并在正式淘汰时更新最终决定。"""
    metadata = item.get("reddit_filter_metadata")
    if not isinstance(metadata, dict):
        metadata = {
            "stages": [],
            "final_decision": "pending",
            "final_reason_codes": [],
        }
        item["reddit_filter_metadata"] = metadata
    stages = metadata.get("stages")
    if not isinstance(stages, list):
        stages = []
        metadata["stages"] = stages
    stages.append(stage_result)
    if stage_result.get("decision") == "drop":
        metadata["final_decision"] = "drop"
        metadata["final_reason_codes"] = list(
            stage_result.get("reason_codes", [])
        )


def reddit_filter_stage(item: Dict, name: str) -> Dict:
    """按名称读取最近一次 Reddit 筛选阶段结果。"""
    metadata = item.get("reddit_filter_metadata", {})
    stages = metadata.get("stages", []) if isinstance(metadata, dict) else []
    for stage in reversed(stages):
        if isinstance(stage, dict) and stage.get("stage") == name:
            return stage
    return {}
