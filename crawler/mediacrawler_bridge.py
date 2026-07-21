# crawler/mediacrawler_bridge.py
"""
MediaCrawler 调度封装
支持通过 subprocess 调用 MediaCrawler CLI，或直接导入其核心模块
"""
import os
import sys
import subprocess
import json
from typing import Optional
import config


class MediaCrawlerBridge:
    """MediaCrawler 桥接器"""

    def __init__(self, platform: Optional[str] = None):
        self.platform = platform or config.CRAWL_PLATFORM
        self.base_path = config.MEDIACRAWLER_PATH
        self.crawl_type = config.CRAWL_TYPE
        self.keywords = config.SEARCH_KEYWORDS

    def run(self) -> bool:
        """
        执行 MediaCrawler 爬取
        支持两种模式：
        1. CLI 模式：调用 MediaCrawler 的命令行接口
        2. 直接导入模式：直接使用 MediaCrawler 的核心函数
        """
        # 检查 MediaCrawler 是否存在
        if not os.path.exists(self.base_path):
            print(f"   ⚠️ MediaCrawler 未找到: {self.base_path}")
            print("   请先 clone: git clone https://github.com/NanmiCoder/MediaCrawler.git")
            return False

        # 模式1: CLI 调用（推荐，更稳定）
        return self._run_cli()

    def _run_cli(self) -> bool:
        """通过 CLI 调用 MediaCrawler"""
        try:
            # MediaCrawler 的 CLI 入口
            # 参考: https://github.com/NanmiCoder/MediaCrawler
            script_path = os.path.join(self.base_path, "main.py")

            if not os.path.exists(script_path):
                print(f"   ❌ MediaCrawler main.py 不存在")
                return False

            # 构建命令
            # 示例: python main.py --platform xiaohongshu --type search --keyword "AI Agent"
            cmd = [
                sys.executable,
                script_path,
                "--platform", self.platform,
                "--type", self.crawl_type,
                "--keyword", self.keywords[0] if self.keywords else "AI"
            ]

            print(f"   📡 执行: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                print("   ✅ MediaCrawler 执行成功")
                # 数据默认保存在 MediaCrawler/data/ 目录
                # 复制到项目的 data/ 目录
                self._copy_data()
                return True
            else:
                print(f"   ❌ MediaCrawler 执行失败: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print("   ❌ MediaCrawler 执行超时")
            return False
        except Exception as e:
            print(f"   ❌ MediaCrawler 执行异常: {e}")
            return False

    def _copy_data(self):
        """将 MediaCrawler 的数据复制到项目 data/ 目录"""
        import shutil
        src_dir = os.path.join(self.base_path, "data")
        dst_dir = "./data"

        if os.path.exists(src_dir):
            os.makedirs(dst_dir, exist_ok=True)
            for filename in os.listdir(src_dir):
                src_file = os.path.join(src_dir, filename)
                dst_file = os.path.join(dst_dir, filename)
                if os.path.isfile(src_file):
                    shutil.copy2(src_file, dst_file)
            print(f"   📂 数据已复制到 {dst_dir}")