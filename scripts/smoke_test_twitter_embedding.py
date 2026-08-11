"""在启动 Twitter 爬取前验证独立 Embedding 服务。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from analyzer.twitter_embedding import (
    TwitterEmbeddingError,
    probe_twitter_embedding_service,
)


def main() -> int:
    if not config.TWITTER_EMBEDDING_ENABLED:
        print(
            "Twitter Embedding 未启用；请在 .env 设置 "
            "TWITTER_EMBEDDING_ENABLED=true"
        )
        return 2
    try:
        dimensions = probe_twitter_embedding_service()
    except TwitterEmbeddingError as exc:
        print(f"Twitter Embedding 检查失败: {exc}")
        return 2
    print(
        "Twitter Embedding 检查成功: "
        f"model={config.TWITTER_EMBEDDING_MODEL}, "
        f"dimensions={dimensions}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
