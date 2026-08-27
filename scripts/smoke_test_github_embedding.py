"""Test the configured GitHub Embedding endpoint with one keyword."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from analyzer.github_embedding import (
    GithubEmbeddingError,
    probe_github_embedding_service,
)


def main() -> int:
    try:
        dimensions = probe_github_embedding_service()
    except GithubEmbeddingError as exc:
        print(f"GitHub Embedding 检查失败: {exc}")
        return 2
    print(
        "GitHub Embedding 检查成功: "
        f"model={config.GITHUB_EMBEDDING_MODEL}, dimensions={dimensions}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
