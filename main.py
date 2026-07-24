"""AI Content Miner 工作流主入口。

职责仅限程序编排：配置检查 → 按平台路由 → 本次爬取 → 数据加载
→ 四层筛选 → 输出 → 企业微信推送。各业务实现仍由已有模块负责。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import config
from crawler.base import CollectorBridge, CrawlRunResult
from crawler.factory import build_collector
from utils.parser import load_articles
from analyzer.filter import multi_stage_filter

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIG = 2
EXIT_CRAWLER = 3
EXIT_NO_DATA = 4
EXIT_NOTIFY = 5
EXIT_STATE = 6


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_runtime_config(bridge: CollectorBridge) -> List[str]:
    """在爬虫启动前检查完整工作流所需的关键配置。"""
    if getattr(bridge, "platform", "") == "x":
        from workflows.twitter import validate_twitter_runtime_config

        return validate_twitter_runtime_config(bridge)

    errors: List[str] = []

    for module_name in ("openai", "requests"):
        if importlib.util.find_spec(module_name) is None:
            errors.append(
                f"缺少项目依赖 {module_name}；请先运行 "
                "python3 -m pip install -r requirements.txt"
            )

    api_key = str(getattr(config, "API_KEY", "")).strip()
    api_placeholders = {"your-api-key-here", "sk-xxxxx", "your-key"}
    if not api_key or api_key.lower() in api_placeholders:
        errors.append("API_KEY 未配置或仍是占位值")

    base_url = str(getattr(config, "BASE_URL", "")).strip()
    if not _is_http_url(base_url):
        errors.append("BASE_URL 必须是有效的 http/https URL")
    if not str(getattr(config, "MODEL_NAME", "")).strip():
        errors.append("MODEL_NAME 不能为空")

    webhook = str(getattr(config, "WECOM_WEBHOOK", "")).strip()
    webhook_placeholders = ("your-webhook-key", "your-key", "example.com")
    if not _is_http_url(webhook):
        errors.append("WECOM_WEBHOOK 必须是有效的 http/https URL")
    elif any(placeholder in webhook.lower() for placeholder in webhook_placeholders):
        errors.append("WECOM_WEBHOOK 未配置或仍包含占位值")

    report_base_url = str(getattr(config, "REPORT_BASE_URL", "")).strip()
    if not _is_http_url(report_base_url):
        errors.append("REPORT_BASE_URL 必须是有效的 http/https URL")

    score_threshold = getattr(config, "SCORE_THRESHOLD", None)
    if (
        not isinstance(score_threshold, (int, float))
        or isinstance(score_threshold, bool)
        or not 0 <= score_threshold <= 10
    ):
        errors.append("SCORE_THRESHOLD 必须是 0 到 10 之间的数字")

    errors.extend(bridge.validate())
    return errors


def generate_reports(scored_items: List[Dict]) -> Tuple[List[Dict], int]:
    """仅对通过四层筛选且 0–10 综合分达标的文章生成输出。"""
    from output.generator import generate_output
    from utils.raditer import log_decision

    print("\n📝 [5/6] 生成报告...")

    final_items: List[Dict] = []
    generated_count = 0
    score_threshold = float(getattr(config, "SCORE_THRESHOLD", 6.0))

    for index, item in enumerate(scored_items, start=1):
        article = item.get("article", {})
        title = article.get("title", "无标题")[:25]
        total_score = item.get("total_score", 0)

        if total_score < score_threshold:
            print(
                f"   ⏭️ 分数不足 [{index}/{len(scored_items)}] {title} "
                f"→ {total_score:.2f} < {score_threshold:.2f}"
            )
            continue

        try:
            output_path = generate_output(item)
            if not output_path:
                print(f"   ❌ 未生成输出: {title}")
                continue

            log_decision(item, output_path)
            final_items.append(item)
            generated_count += 1
            print(
                f"   ✅ [{index}/{len(scored_items)}] {title} → {output_path}"
            )
        except Exception as exc:
            print(f"   ❌ 处理异常: {title} - {exc}")

        time.sleep(1)

    print(f"   ✅ 生成完成，共 {generated_count} 篇报告")
    return final_items, generated_count


def run_workflow(bridge: CollectorBridge) -> int:
    """运行已通过配置检查的完整工作流，并返回进程退出码。"""
    if getattr(bridge, "platform", "") == "x":
        from workflows.twitter import run_twitter_workflow

        return run_twitter_workflow(bridge)

    print("\n📡 [1/6] 启动数据采集...")
    crawl_result: CrawlRunResult = bridge.run()
    if not crawl_result.success:
        print(f"   ❌ 爬取失败: {crawl_result.error}")
        return EXIT_CRAWLER
    print(f"   ✅ 爬取完成，内容文件 {len(crawl_result.data_files)} 个")

    print("\n📂 [2/6] 加载本次运行数据...")
    articles = load_articles(
        crawl_result.data_files,
        platform=bridge.platform,
        allow_manual_fallback=False,
    )
    if not articles:
        print("   ❌ 本次运行没有可处理的内容数据，流程终止")
        return EXIT_NO_DATA
    print(f"   ✅ 加载 {len(articles)} 篇文章")

    print("\n🧠 [3/6] 执行四层筛选（规则 → 语义去重 → 评论区 → 博主画像）...")
    passed_items: List[Dict] = []
    filtered_count = 0

    for idx, article in enumerate(articles, start=1):
        result = multi_stage_filter(
            article,
            existing_articles=None,
            enable_semantic=True,
            enable_comment=True,
            enable_author_profile=True,
        )

        title = article.get("title", "无标题")[:25]
        if not result.passed:
            filtered_count += 1
            reason = (
                result.rule_reason
                or result.semantic_reason
                or result.comment_reason
                or result.author_reason
            )
            print(
                f"   ⏭️ 淘汰 [{idx}/{len(articles)}] {title} → {reason}"
            )
            continue

        total_score = result.total_score()
        scored_item = {
            "article": article,
            "total_score": total_score,
            "filter_result": result.to_dict(),
            "blogger_weight": 1.0,
        }
        passed_items.append(scored_item)
        print(
            f"   ✅ 通过 [{idx}/{len(articles)}] {title} "
            f"→ 综合得分 {total_score:.2f}/10"
        )

    print(
        f"   ✅ 筛选完成：通过 {len(passed_items)} 篇，"
        f"淘汰 {filtered_count} 篇"
    )

    final_items, generated_count = generate_reports(passed_items)

    print("\n📤 [6/6] 推送企业微信...")
    if final_items:
        from notifier.wecom import send_to_wecom
        if not send_to_wecom(final_items):
            print("   ❌ 推送失败")
            return EXIT_NOTIFY
    else:
        print("   ℹ️ 无高分文章，跳过推送")

    state_error = bridge.acknowledge()
    if state_error:
        print(f"   ❌ 采集状态保存失败: {state_error}")
        return EXIT_STATE

    print("\n" + "=" * 70)
    print("🎉 工作流执行完毕！")
    print("📊 统计：")
    print(f"   - 读取文章: {len(articles)} 篇")
    print(f"   - 通过筛选: {len(passed_items)} 篇")
    print(f"   - 四层筛选淘汰: {filtered_count} 篇")
    print(f"   - 生成报告: {generated_count} 篇")
    print(f"   - 推送报告: {len(final_items)} 篇")
    print("=" * 70)
    return EXIT_OK


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Content Miner 工作流")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="仅检查运行配置、采集器依赖和本地会话，不启动爬虫",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_argument_parser().parse_args(argv)

    print("=" * 70)
    print("🚀 AI Content Miner - 全自动化知识工作流")
    print(f"⏰ 启动时间: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 70)

    bridge = build_collector()
    config_errors = validate_runtime_config(bridge)
    if config_errors:
        print("\n❌ 配置检查失败：")
        for error in config_errors:
            print(f"   - {error}")
        return EXIT_CONFIG

    if (
        getattr(bridge, "platform", "") != "x"
        and (
            "127.0.0.1" in config.REPORT_BASE_URL
            or "localhost" in config.REPORT_BASE_URL
        )
    ):
        print(
            "\n⚠️ REPORT_BASE_URL 为本地地址，企业员工可能无法访问生成的报告"
        )

    print("\n✅ 配置检查通过")
    if args.check_config:
        return EXIT_OK
    return run_workflow(bridge)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断执行")
        sys.exit(130)
    except Exception as exc:
        print(f"\n❌ 执行异常: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(EXIT_UNEXPECTED)
