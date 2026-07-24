"""AI Content Miner 跨平台结构化信息流主入口。"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlparse

import config
from analyzer.comment_filter import CommentFilterConfigError
from analyzer.embedding_filter import EmbeddingFilterError
from analyzer.enricher import EnrichmentConfigError, enrich_items
from analyzer.pipeline import run_filter_pipeline
from crawler.base import CollectorBridge, CrawlRunResult
from crawler.factory import build_collector
from output.feed_renderer import FeedRenderError, render_platform_feed
from utils.parser import load_articles
from utils.result_store import ResultStoreError, append_processed_items


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


def _is_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_placeholder(value: object, placeholders: Sequence[str]) -> bool:
    normalized = str(value or "").strip().casefold()
    return not normalized or any(
        placeholder.casefold() in normalized for placeholder in placeholders
    )


def validate_runtime_config(bridge: CollectorBridge) -> List[str]:
    """在采集前校验核心模型、可选通知和平台采集配置。"""
    errors: List[str] = []
    required_modules = ["openai"]
    if getattr(config, "ENABLE_WECOM", False):
        required_modules.append("requests")
    for module_name in required_modules:
        if importlib.util.find_spec(module_name) is None:
            errors.append(
                f"缺少项目依赖 {module_name}；请先运行 "
                "python3 -m pip install -r requirements.txt"
            )

    if _is_placeholder(
        getattr(config, "API_KEY", ""),
        ("your-api-key-here", "sk-xxxxx", "your-key"),
    ):
        errors.append("API_KEY 未配置或仍是占位值")
    if not _is_http_url(getattr(config, "BASE_URL", "")):
        errors.append("BASE_URL 必须是有效的 http/https URL")
    if not str(getattr(config, "MODEL_NAME", "") or "").strip():
        errors.append("MODEL_NAME 不能为空")
    if not str(getattr(config, "EMBEDDING_MODEL", "") or "").strip():
        errors.append("EMBEDDING_MODEL 不能为空")
    if getattr(config, "EMBEDDING_FILTER_MODE", "") not in {
        "shadow",
        "enforce",
    }:
        errors.append("EMBEDDING_FILTER_MODE 只能是 shadow 或 enforce")

    if getattr(config, "ENABLE_WECOM", False):
        webhook = getattr(config, "WECOM_WEBHOOK", "")
        if not _is_http_url(webhook) or _is_placeholder(
            webhook,
            ("your-webhook-key", "your-key", "example.com"),
        ):
            errors.append("启用企业微信时必须配置有效的 WECOM_WEBHOOK")
        if not _is_http_url(getattr(config, "REPORT_BASE_URL", "")):
            errors.append("启用企业微信时 REPORT_BASE_URL 必须是有效 URL")

    errors.extend(bridge.validate())
    return errors


def _finalize_items(all_items: Sequence[Dict], kept_items: Sequence[Dict]) -> None:
    """为所有候选项补齐最终决定和处理时间。"""
    kept_objects = {id(item) for item in kept_items}
    processed_at = datetime.now(timezone.utc)
    for item in all_items:
        metadata = item.setdefault(
            "filter_metadata",
            {
                "stages": [],
                "final_decision": "pending",
                "final_reason_codes": [],
            },
        )
        if id(item) in kept_objects:
            metadata["final_decision"] = "keep"
            metadata["final_reason_codes"] = ["FILTER_PIPELINE_PASSED"]
        elif metadata.get("final_decision") == "pending":
            metadata["final_decision"] = "drop"
            metadata["final_reason_codes"] = ["FILTER_PIPELINE_INCOMPLETE"]
        item["processed_at"] = processed_at


def _comment_provider(bridge: CollectorBridge) -> Optional[object]:
    provider = getattr(bridge, "fetch_comments", None)
    return bridge if callable(provider) else None


def run_workflow(
    bridge: CollectorBridge,
    embedding_client: Optional[object] = None,
    enrichment_client: Optional[object] = None,
) -> int:
    """运行一次完整批处理，并返回明确的退出状态。"""
    print("\n[1/7] 启动数据采集")
    crawl_result: CrawlRunResult = bridge.run()
    if not crawl_result.success:
        print(f"采集失败：{crawl_result.error}")
        return EXIT_CRAWLER
    print(f"采集完成，本次内容文件 {len(crawl_result.data_files)} 个")

    print("\n[2/7] 加载并标准化本次数据")
    items = load_articles(
        crawl_result.data_files,
        platform=bridge.platform,
        allow_manual_fallback=False,
    )
    if not items:
        print("本次运行没有可处理的内容")
        return EXIT_NO_DATA
    print(f"已加载 {len(items)} 条内容")

    print("\n[3/7] 执行三层筛选")
    try:
        filtered = run_filter_pipeline(
            items,
            embedding_client=embedding_client,
            comment_provider=_comment_provider(bridge),
        )
    except EmbeddingFilterError as exc:
        print(f"Embedding 筛选失败：{exc}")
        return EXIT_EMBEDDING
    except CommentFilterConfigError as exc:
        print(f"评论筛选配置无效：{exc}")
        return EXIT_CONFIG
    print(
        f"筛选完成，保留 {len(filtered['passed'])} 条，"
        f"删除 {len(filtered['dropped'])} 条"
    )

    print("\n[4/7] 生成极简摘要和分层标签")
    try:
        kept_items = enrich_items(
            filtered["passed"],
            client=enrichment_client,
        )
    except EnrichmentConfigError as exc:
        print(f"摘要或标签配置无效：{exc}")
        return EXIT_CONFIG
    _finalize_items(filtered["all_items"], kept_items)
    print(f"已整理 {len(kept_items)} 条保留内容")

    print("\n[5/7] 写入结构化结果")
    try:
        result_path = append_processed_items(
            bridge.platform,
            filtered["all_items"],
        )
    except ResultStoreError as exc:
        print(str(exc))
        return EXIT_STORE
    print(f"结构化结果已写入 {result_path}")

    print("\n[6/7] 更新平台聚合页面")
    try:
        report_path = render_platform_feed(bridge.platform)
    except (FeedRenderError, ResultStoreError) as exc:
        print(str(exc))
        return EXIT_RENDER
    print(f"聚合页面已更新 {report_path}")

    state_error = bridge.acknowledge()
    if state_error:
        print(f"采集状态保存失败：{state_error}")
        return EXIT_STATE

    print("\n[7/7] 可选通知")
    if getattr(config, "ENABLE_WECOM", False):
        from notifier.wecom import send_to_wecom

        if not send_to_wecom(kept_items, platform=bridge.platform):
            print("企业微信通知失败，结构化结果和采集状态已保留")
            return EXIT_NOTIFY
        print("企业微信通知完成")
    else:
        print("企业微信通知未启用")

    print("\n工作流执行完毕")
    print(f"候选内容：{len(items)}")
    print(f"最终保留：{len(kept_items)}")
    print(f"最终删除：{len(filtered['dropped'])}")
    return EXIT_OK


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Content Miner 工作流")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="仅检查配置、采集器依赖和本地会话，不启动采集",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_argument_parser().parse_args(argv)
    print("=" * 70)
    print("AI Content Miner - 跨平台结构化信息流")
    print(f"启动时间：{datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 70)

    bridge = build_collector()
    config_errors = validate_runtime_config(bridge)
    if config_errors:
        print("\n配置检查失败：")
        for error in config_errors:
            print(f"- {error}")
        return EXIT_CONFIG

    print("\n配置检查通过")
    if args.check_config:
        return EXIT_OK
    return run_workflow(bridge)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n用户中断执行")
        sys.exit(130)
    except Exception as exc:
        print(f"\n执行异常：{type(exc).__name__}: {exc}")
        sys.exit(EXIT_UNEXPECTED)
