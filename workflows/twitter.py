"""仅供 Twitter 使用的结构化信息流工作流。"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlparse

import config
from analyzer.twitter_comments import (
    TwitterCommentConfigError,
    twitter_comment_settings,
)
from analyzer.twitter_embedding import (
    TwitterEmbeddingError,
    validate_twitter_embedding_config,
)
from analyzer.twitter_enricher import (
    TwitterEnrichmentConfigError,
    enrich_twitter_items,
    validate_twitter_enrichment_config,
)
from analyzer.twitter_pipeline import run_twitter_filters
from analyzer.twitter_rules import validate_twitter_rule_config
from crawler.base import CollectorBridge, CrawlRunResult
from notifier.twitter_wecom import (
    send_twitter_wecom,
    validate_twitter_wecom_config,
)
from output.twitter_feed import (
    TwitterFeedRenderError,
    render_twitter_feed,
)
from utils.twitter_parser import load_twitter_items
from utils.twitter_result_store import (
    TwitterResultStoreError,
    append_twitter_results,
)


EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIG = 2
EXIT_CRAWLER = 3
EXIT_NO_DATA = 4
EXIT_NOTIFY = 5
EXIT_STATE = 6
EXIT_EMBEDDING = 7
EXIT_STORE = 8
EXIT_RENDER = 9


def _http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_twitter_runtime_config(
    bridge: CollectorBridge,
) -> List[str]:
    """只校验 Twitter 新流程需要的配置。"""
    errors: List[str] = []
    modules = ["openai"]
    if config.TWITTER_ENABLE_WECOM:
        modules.append("requests")
    for module_name in modules:
        if importlib.util.find_spec(module_name) is None:
            errors.append(
                f"缺少项目依赖 {module_name}；请先安装 requirements.txt"
            )

    api_key = str(config.API_KEY or "").strip()
    if not api_key or api_key.casefold() in {
        "your-api-key-here",
        "sk-xxxxx",
        "your-key",
    }:
        errors.append("API_KEY 未配置或仍是占位值")
    if not _http_url(config.BASE_URL):
        errors.append("BASE_URL 必须是有效的 http/https URL")
    if not str(config.MODEL_NAME or "").strip():
        errors.append("MODEL_NAME 不能为空")

    try:
        validate_twitter_rule_config()
    except ValueError as exc:
        errors.append(str(exc))
    # Embedding 关闭时不要求模型和批次配置可用，避免可选能力阻塞主流程。
    if getattr(config, "TWITTER_EMBEDDING_ENABLED", True):
        try:
            validate_twitter_embedding_config()
        except TwitterEmbeddingError as exc:
            errors.append(str(exc))
    try:
        twitter_comment_settings()
    except TwitterCommentConfigError as exc:
        errors.append(str(exc))
    try:
        validate_twitter_enrichment_config()
    except TwitterEnrichmentConfigError as exc:
        errors.append(str(exc))
    if (
        not isinstance(config.TWITTER_FEED_RETENTION_DAYS, int)
        or config.TWITTER_FEED_RETENTION_DAYS <= 0
    ):
        errors.append("TWITTER_FEED_RETENTION_DAYS 必须是正整数")
    if (
        not isinstance(config.TWITTER_FEED_MAX_ITEMS, int)
        or config.TWITTER_FEED_MAX_ITEMS <= 0
    ):
        errors.append("TWITTER_FEED_MAX_ITEMS 必须是正整数")
    errors.extend(validate_twitter_wecom_config())
    errors.extend(bridge.validate())
    return errors


def _finalize(
    all_items: Sequence[Dict],
    kept_items: Sequence[Dict],
) -> None:
    kept_objects = {id(item) for item in kept_items}
    processed_at = datetime.now(timezone.utc)
    for item in all_items:
        metadata = item["filter_metadata"]
        if id(item) in kept_objects:
            metadata["final_decision"] = "keep"
            metadata["final_reason_codes"] = [
                "TWITTER_FILTER_PIPELINE_PASSED"
            ]
        elif metadata.get("final_decision") == "pending":
            metadata["final_decision"] = "drop"
            metadata["final_reason_codes"] = [
                "TWITTER_FILTER_PIPELINE_INCOMPLETE"
            ]
        item["processed_at"] = processed_at


def run_twitter_workflow(
    bridge: CollectorBridge,
    embedding_client: Optional[object] = None,
    enrichment_client: Optional[object] = None,
) -> int:
    """运行 Twitter 专用流程，不调用任何旧平台处理模块。"""
    print("\n[Twitter 1/7] 启动数据采集")
    crawl_result: CrawlRunResult = bridge.run()
    if not crawl_result.success:
        print(f"Twitter 采集失败：{crawl_result.error}")
        return EXIT_CRAWLER

    print("\n[Twitter 2/7] 加载并标准化本次数据")
    try:
        items = load_twitter_items(crawl_result.data_files)
    except ValueError as exc:
        print(f"Twitter 数据加载失败：{exc}")
        return EXIT_UNEXPECTED
    if not items:
        print("本次运行没有可处理的 Twitter 内容")
        return EXIT_NO_DATA

    print("\n[Twitter 3/7] 执行三层筛选")
    reply_provider = (
        bridge
        if callable(getattr(bridge, "fetch_replies", None))
        else None
    )
    try:
        filtered = run_twitter_filters(
            items,
            embedding_client=embedding_client,
            reply_provider=reply_provider,
        )
    except TwitterEmbeddingError as exc:
        print(f"Twitter Embedding 筛选失败：{exc}")
        return EXIT_EMBEDDING
    except TwitterCommentConfigError as exc:
        print(f"Twitter 回复筛选配置无效：{exc}")
        return EXIT_CONFIG

    print("\n[Twitter 4/7] 生成极简摘要和分层标签")
    try:
        kept_items = enrich_twitter_items(
            filtered["passed"],
            client=enrichment_client,
        )
    except TwitterEnrichmentConfigError as exc:
        print(f"Twitter 摘要或标签配置无效：{exc}")
        return EXIT_CONFIG
    _finalize(filtered["all_items"], kept_items)

    print("\n[Twitter 5/7] 写入结构化结果")
    try:
        result_path = append_twitter_results(filtered["all_items"])
    except TwitterResultStoreError as exc:
        print(str(exc))
        return EXIT_STORE
    print(f"Twitter 结构化结果已写入 {result_path}")

    print("\n[Twitter 6/7] 更新聚合页面")
    try:
        report_path = render_twitter_feed()
    except (TwitterFeedRenderError, TwitterResultStoreError) as exc:
        print(str(exc))
        return EXIT_RENDER
    print(f"Twitter 聚合页面已更新 {report_path}")

    state_error = bridge.acknowledge()
    if state_error:
        print(f"Twitter 采集状态保存失败：{state_error}")
        return EXIT_STATE

    print("\n[Twitter 7/7] 可选通知")
    if config.TWITTER_ENABLE_WECOM and not send_twitter_wecom(kept_items):
        print("Twitter 通知失败，结果和采集状态已保留")
        return EXIT_NOTIFY
    if not config.TWITTER_ENABLE_WECOM:
        print("Twitter 企业微信通知未启用")

    print(
        f"Twitter 工作流完成：候选 {len(items)}，"
        f"保留 {len(kept_items)}，删除 {len(filtered['dropped'])}"
    )
    return EXIT_OK
