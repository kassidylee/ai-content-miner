"""采集器之间共享的最小接口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol, Tuple


@dataclass(frozen=True)
class CrawlRunResult:
    """一次采集运行的可审计结果。"""

    success: bool
    data_files: Tuple[Path, ...] = ()
    command: Tuple[str, ...] = ()
    output_dir: Optional[Path] = None
    returncode: Optional[int] = None
    error: str = ""


class CollectorBridge(Protocol):
    """主工作流实际依赖的采集器能力。"""

    platform: str

    def validate(self) -> List[str]:
        """返回阻止采集启动的配置错误。"""

    def run(self) -> CrawlRunResult:
        """执行一次采集并仅返回本次运行产生的数据文件。"""

    def acknowledge(self) -> str:
        """在完整工作流成功后确认本次数据，失败时返回错误信息。"""
