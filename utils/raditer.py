# utils/raditer.py
"""
RadIter 决策日志模块
"""
import os
import json
from datetime import datetime

import config

LOG_FILE = config.RADITER_LOG_FILE


def log_decision(item: dict, output_path: str):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    article = item.get("article", {})
    entry = {
        "timestamp": datetime.now().isoformat(),
        "title": article.get("title", "无标题"),
        "score": item.get("total_score", 0),
        "output": output_path,
        "source": article.get("source", "未知"),
        "dimensions": item.get("dimensions", []),
        "scores": item.get("scores", []),
        "is_second_hand": item.get("is_second_hand", False),
        "original_source": item.get("original_source", "")
    }

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_recent_decisions(limit: int = 100) -> list:
    if not os.path.exists(LOG_FILE):
        return []

    decisions = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    decisions.append(json.loads(line))
                except:
                    continue

    return decisions[-limit:]