# main.py
"""
AI Content Miner - 全自动化工作流主入口

流程：爬取 → 加载 → lingzao分析 → 规则过滤 → AI评分 → RAL溯源 → 生成输出 → 推送
所有文章解析函数统一从 utils.parser 导入。
"""

import os
import sys
import time
from datetime import datetime
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

from utils.parser import load_articles, source_classify
from crawler.mediacrawler_bridge import MediaCrawlerBridge
from analyzer.filter import rule_filter, get_blogger_weight
from analyzer.scorer import score_and_classify
from analyzer.ral import ral_pipeline
from analyzer.lingzao_adapter import LingzaoAnalyzer
from output.generator import generate_output
from notifier.wecom import send_to_wecom
from utils.raditer import log_decision


def normalize_source(source: str) -> str:
    result = source_classify(source)
    if result == "未知" and source and source != "未知":
        return source
    return result


def sanitize_filename(title: str) -> str:
    import re
    safe = re.sub(r'[^\w\s\u4e00-\u9fff]', '', title)
    safe = safe.strip()[:40].replace(' ', '_')
    return safe or "未命名"


def main():
    print("=" * 70)
    print("🚀 AI Content Miner - 全自动化知识工作流")
    print(f"⏰ 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Step 1: 爬取
    print("\n📡 [1/6] 启动数据采集...")
    if os.path.exists(config.MEDIACRAWLER_PATH):
        crawler = MediaCrawlerBridge()
        crawler.run()
        print("   ✅ 爬取完成")
    else:
        print(f"   ⚠️ MediaCrawler 未找到: {config.MEDIACRAWLER_PATH}")
        print("   📌 请先执行: git clone https://github.com/NanmiCoder/MediaCrawler.git")
        print("   📌 或手动将文章放入 ./articles/ 目录")
        print("   ⏭️ 跳过爬取步骤")

    # Step 2: 加载数据
    print("\n📂 [2/6] 加载数据...")
    articles = load_articles()
    if not articles:
        print("   ❌ 没有数据，流程终止")
        return
    print(f"   ✅ 加载 {len(articles)} 篇文章")

    # Step 3: lingzao 分析
    print("\n🧠 [3/6] lingzao-skill 内容分析...")
    lingzao = LingzaoAnalyzer()
    for idx, art in enumerate(articles):
        try:
            art["lingzao_analysis"] = lingzao.analyze(art)
            if (idx + 1) % 10 == 0:
                print(f"   📊 进度: {idx+1}/{len(articles)}")
        except Exception as e:
            print(f"   ⚠️ 分析失败: {art.get('title', '无标题')[:20]} - {e}")
            art["lingzao_analysis"] = {"error": str(e)}
        time.sleep(0.5)
    print(f"   ✅ 分析完成")

    # Step 4: 过滤 + 评分
    print("\n📊 [4/6] 规则过滤 + AI 评分...")
    scored_items = []
    filtered_count = 0

    for idx, art in enumerate(articles):
        passed, reason = rule_filter(art)
        if not passed:
            filtered_count += 1
            print(f"   ⏭️ 跳过 [{idx+1}/{len(articles)}] {art.get('title', '无标题')[:25]} → {reason}")
            continue

        weight = get_blogger_weight(art)
        try:
            result = score_and_classify(art)
            result["blogger_weight"] = weight
            result["total_score"] = min(10.0, result.get("total_score", 0) * weight)
            result["lingzao"] = art.get("lingzao_analysis", {})
            scored_items.append(result)
            print(f"   📊 [{idx+1}/{len(articles)}] {art.get('title', '无标题')[:25]} → {result['total_score']:.1f} 分")
        except Exception as e:
            print(f"   ❌ 评分失败: {art.get('title', '无标题')[:25]} - {e}")

        time.sleep(config.REQUEST_INTERVAL)

    scored_items.sort(key=lambda x: x.get("total_score", 0), reverse=True)
    print(f"   ✅ 评分完成：通过 {len(scored_items)} 篇，过滤 {filtered_count} 篇")

    # Step 5: RAL + 生成输出
    print("\n📝 [5/6] RAL 溯源增强 + 生成报告...")
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    final_items = []
    generated_count = 0

    for idx, item in enumerate(scored_items):
        if item["total_score"] < config.SCORE_THRESHOLD:
            print(f"   ⏭️ 分数不足 [{idx+1}/{len(scored_items)}] {item.get('article', {}).get('title', '无标题')[:25]} → {item['total_score']:.1f} < {config.SCORE_THRESHOLD}")
            continue

        try:
            enriched = ral_pipeline(item)
            output_path = generate_output(enriched)
            if output_path:
                log_decision(enriched, output_path)
                final_items.append(enriched)
                generated_count += 1
                print(f"   ✅ [{idx+1}/{len(scored_items)}] {enriched.get('article', {}).get('title', '无标题')[:25]} → {os.path.basename(output_path)}")
        except Exception as e:
            print(f"   ❌ 处理异常: {item.get('article', {}).get('title', '无标题')[:25]} - {e}")

        time.sleep(1)

    print(f"   ✅ 生成完成，共 {generated_count} 篇报告")

    # Step 6: 企业微信推送
    print("\n📤 [6/6] 推送企业微信...")
    if final_items:
        try:
            success = send_to_wecom(final_items)
            print(f"   {'✅' if success else '⚠️'} 推送{'成功' if success else '失败，请检查 Webhook 配置'}")
        except Exception as e:
            print(f"   ❌ 推送异常: {e}")
    else:
        print("   ℹ️ 无高分文章，跳过推送")

    print("\n" + "=" * 70)
    print("🎉 工作流执行完毕！")
    print(f"📊 统计：")
    print(f"   - 读取文章: {len(articles)} 篇")
    print(f"   - 通过过滤: {len(scored_items)} 篇")
    print(f"   - 生成报告: {generated_count} 篇")
    print(f"   - 推送报告: {len(final_items)} 篇")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断执行")
    except Exception as e:
        print(f"\n❌ 执行异常: {e}")
        import traceback
        traceback.print_exc()