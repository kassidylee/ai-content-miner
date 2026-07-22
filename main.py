"""AI Content Miner 工作流主入口。

职责仅限程序编排：配置检查 → 本次爬取 → 本次数据加载 → 分析/过滤/评分
→ 可选溯源 → 输出 → 企业微信推送。各业务实现仍由已有模块负责。
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
from crawler.mediacrawler_bridge import CrawlRunResult, MediaCrawlerBridge
from utils.parser import load_articles


EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIG = 2
EXIT_CRAWLER = 3
EXIT_NO_DATA = 4
EXIT_NOTIFY = 5


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_runtime_config(bridge: MediaCrawlerBridge) -> List[str]:
    """在爬虫启动前检查完整工作流所需的关键配置。"""
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

    errors.extend(bridge.validate())
    return errors


def analyze_articles(articles: List[Dict]) -> None:
    """按配置执行 lingzao 分析；禁用时不做空调用。"""
    if not getattr(config, "ENABLE_LINGZAO_ANALYSIS", False):
        print("\n🧠 [3/6] lingzao 分析已禁用，明确跳过")
        return

    from analyzer.lingzao_adapter import LingzaoAnalyzer

    print("\n🧠 [3/6] lingzao-skill 内容分析...")
    lingzao = LingzaoAnalyzer()
    for index, article in enumerate(articles, start=1):
        try:
            article["lingzao_analysis"] = lingzao.analyze(article)
            if index % 10 == 0:
                print(f"   📊 进度: {index}/{len(articles)}")
        except Exception as exc:
            title = article.get("title", "无标题")[:20]
            print(f"   ⚠️ 分析失败: {title} - {exc}")
            article["lingzao_analysis"] = {"error": str(exc)}
        time.sleep(0.5)
    print("   ✅ 分析完成")


def score_articles(articles: List[Dict]) -> Tuple[List[Dict], int]:
    from analyzer.filter import get_blogger_weight, rule_filter
    from analyzer.scorer import score_and_classify

    print("\n📊 [4/6] 规则过滤 + AI 评分...")
    scored_items: List[Dict] = []
    filtered_count = 0

    for index, article in enumerate(articles, start=1):
        passed, reason = rule_filter(article)
        title = article.get("title", "无标题")[:25]
        if not passed:
            filtered_count += 1
            print(f"   ⏭️ 跳过 [{index}/{len(articles)}] {title} → {reason}")
            continue

        weight = get_blogger_weight(article)
        try:
            result = score_and_classify(article)
            result["blogger_weight"] = weight
            result["total_score"] = min(
                10.0, result.get("total_score", 0) * weight
            )
            result["lingzao"] = article.get("lingzao_analysis", {})
            scored_items.append(result)
            print(
                f"   📊 [{index}/{len(articles)}] {title} "
                f"→ {result['total_score']:.1f} 分"
            )
        except Exception as exc:
            print(f"   ❌ 评分失败: {title} - {exc}")

        time.sleep(config.REQUEST_INTERVAL)

    scored_items.sort(key=lambda item: item.get("total_score", 0), reverse=True)
    print(
        f"   ✅ 评分完成：通过 {len(scored_items)} 篇，过滤 {filtered_count} 篇"
    )
    return scored_items, filtered_count


def generate_reports(scored_items: List[Dict]) -> Tuple[List[Dict], int]:
    from output.generator import generate_output
    from utils.raditer import log_decision

    retrieval_enabled = getattr(config, "ENABLE_RETRIEVAL", False)
    if retrieval_enabled:
        from analyzer.ral import ral_pipeline

        print("\n📝 [5/6] RAL 来源识别 + 生成报告...")
    else:
        ral_pipeline = None
        print("\n📝 [5/6] RAL 来源识别已禁用；仅生成报告...")

    final_items: List[Dict] = []
    generated_count = 0

    for index, item in enumerate(scored_items, start=1):
        article = item.get("article", {})
        title = article.get("title", "无标题")[:25]
        if item["total_score"] < config.SCORE_THRESHOLD:
            print(
                f"   ⏭️ 分数不足 [{index}/{len(scored_items)}] {title} "
                f"→ {item['total_score']:.1f} < {config.SCORE_THRESHOLD}"
            )
            continue

        try:
            enriched = ral_pipeline(item) if ral_pipeline else item
            output_path = generate_output(enriched)
            if not output_path:
                print(f"   ❌ 未生成输出: {title}")
                continue
            log_decision(enriched, output_path)
            final_items.append(enriched)
            generated_count += 1
            print(
                f"   ✅ [{index}/{len(scored_items)}] {title} → {output_path}"
            )
        except Exception as exc:
            print(f"   ❌ 处理异常: {title} - {exc}")

        time.sleep(1)

    print(f"   ✅ 生成完成，共 {generated_count} 篇报告")
    return final_items, generated_count


def run_workflow(bridge: MediaCrawlerBridge) -> int:
    """运行已通过配置检查的完整工作流，并返回进程退出码。"""
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

    analyze_articles(articles)
    scored_items, filtered_count = score_articles(articles)
    final_items, generated_count = generate_reports(scored_items)

    print("\n📤 [6/6] 推送企业微信...")
    if final_items:
        from notifier.wecom import send_to_wecom

        if not send_to_wecom(final_items):
            print("   ❌ 推送失败")
            return EXIT_NOTIFY
    else:
        print("   ℹ️ 无高分文章，跳过推送")

    print("\n" + "=" * 70)
    print("🎉 工作流执行完毕！")
    print("📊 统计：")
    print(f"   - 读取文章: {len(articles)} 篇")
    print(f"   - 通过过滤: {len(scored_items)} 篇")
    print(f"   - 规则过滤: {filtered_count} 篇")
    print(f"   - 生成报告: {generated_count} 篇")
    print(f"   - 推送报告: {len(final_items)} 篇")
    print("=" * 70)
    return EXIT_OK


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Content Miner 工作流")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="仅检查运行配置和 MediaCrawler 版本，不启动爬虫",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_argument_parser().parse_args(argv)

    print("=" * 70)
    print("🚀 AI Content Miner - 全自动化知识工作流")
    print(f"⏰ 启动时间: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 70)

    bridge = MediaCrawlerBridge()
    config_errors = validate_runtime_config(bridge)
    if config_errors:
        print("\n❌ 配置检查失败：")
        for error in config_errors:
            print(f"   - {error}")
        return EXIT_CONFIG

    if "127.0.0.1" in config.REPORT_BASE_URL or "localhost" in config.REPORT_BASE_URL:
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
