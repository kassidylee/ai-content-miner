"""GitHub 专用筛选链路的共享审计工具。"""

from __future__ import annotations

from typing import Dict


def append_github_filter_stage(
    item: Dict,
    stage_result: Dict[str, object],
) -> None:
    """追加阶段结果，并在正式删除时更新最终决定。"""
    metadata = item.setdefault(
        "github_filter_metadata",
        {
            "stages": [],
            "final_decision": "pending",
            "final_reason_codes": [],
        },
    )
    metadata.setdefault("stages", []).append(stage_result)
    if stage_result.get("decision") == "drop":
        metadata["final_decision"] = "drop"
        metadata["final_reason_codes"] = list(
            stage_result.get("reason_codes", [])
        )
