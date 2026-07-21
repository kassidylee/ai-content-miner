# crawler/mediacrawler_bridge.py
"""
MediaCrawler 桥接器
支持平台：xhs（小红书）、zhihu
"""
import os
import sys
import json
import shutil
import subprocess
import re
import time
from typing import List, Dict
from pathlib import Path

import config


class MediaCrawlerBridge:
    def __init__(self):
        self.base_path = Path(config.MEDIACRAWLER_PATH)
        self.platform = config.CRAWL_PLATFORM
        self.crawl_type = config.CRAWL_TYPE
        self.keywords = config.SEARCH_KEYWORDS
        self.limit = getattr(config, 'CRAWL_LIMIT', 20)
        self.data_dir = self.base_path / "data"
        self.target_data_dir = Path(config.DATA_DIR)

    def run(self) -> bool:
        if not self.base_path.exists():
            print(f"   ❌ MediaCrawler 未找到: {self.base_path}")
            return False

        if not self._check_uv():
            print("   ⚠️ uv 未安装，尝试使用系统 Python")
            return self._run_with_system_python()

        success_count = 0
        for keyword in self.keywords:
            print(f"   🔍 爬取关键词: {keyword}")
            try:
                result = self._run_single_keyword(keyword)
                if result:
                    success_count += 1
                    print(f"   ✅ 关键词 '{keyword}' 爬取完成")
                else:
                    print(f"   ⚠️ 关键词 '{keyword}' 爬取失败")
            except Exception as e:
                print(f"   ❌ 关键词 '{keyword}' 异常: {e}")
            time.sleep(3)

        print(f"   📊 完成 {success_count}/{len(self.keywords)} 个关键词")

        if success_count > 0:
            self._copy_data()
            return True
        return False

    def _check_uv(self) -> bool:
        try:
            result = subprocess.run(
                ["uv", "--version"],
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False

    def _run_single_keyword(self, keyword: str) -> bool:
        try:
            if not self._update_config(keyword):
                print(f"   ⚠️ 配置更新失败，尝试 CLI 方式")
                return self._run_cli_mode(keyword)

            cmd = [
                "uv", "run", "main.py",
                "--platform", self._platform_mapping(),
                "--lt", "qrcode",
                "--type", self.crawl_type
            ]

            print(f"   📡 执行: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                print(f"   ❌ 执行失败: {result.stderr[:200]}")
                return False
            return True

        except subprocess.TimeoutExpired:
            print(f"   ❌ 执行超时 (300s)")
            return False
        except Exception as e:
            print(f"   ❌ 执行异常: {e}")
            return False

    def _run_cli_mode(self, keyword: str) -> bool:
        cmd = [
            "uv", "run", "main.py",
            "--platform", self._platform_mapping(),
            "--lt", "qrcode",
            "--type", self.crawl_type,
            "--keyword", keyword
        ]
        if self.limit > 0:
            cmd.extend(["--limit", str(self.limit)])

        try:
            result = subprocess.run(
                cmd,
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=300
            )
            return result.returncode == 0
        except:
            return False

    def _run_with_system_python(self) -> bool:
        print("   📡 使用系统 Python")
        for keyword in self.keywords:
            cmd = [
                sys.executable, "main.py",
                "--platform", self._platform_mapping(),
                "--lt", "qrcode",
                "--type", self.crawl_type,
                "--keyword", keyword
            ]
            try:
                result = subprocess.run(
                    cmd,
                    cwd=self.base_path,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode != 0:
                    print(f"   ⚠️ 关键词 '{keyword}' 失败")
            except Exception as e:
                print(f"   ❌ 异常: {e}")
            time.sleep(3)
        return True

    def _update_config(self, keyword: str) -> bool:
        config_file = self.base_path / "config" / "base_config.py"
        if not config_file.exists():
            config_file = self.base_path / "config.py"
            if not config_file.exists():
                return False

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                content = f.read()

            patterns = [
                (r"SEARCH_KEYWORDS\s*=\s*\[[^\]]*\]", f'SEARCH_KEYWORDS = ["{keyword}"]'),
                (r"search_keywords\s*=\s*\[[^\]]*\]", f'search_keywords = ["{keyword}"]'),
                (r"KEYWORDS\s*=\s*\[[^\]]*\]", f'KEYWORDS = ["{keyword}"]'),
            ]

            modified = False
            for pattern, replacement in patterns:
                if re.search(pattern, content):
                    content = re.sub(pattern, replacement, content)
                    modified = True
                    break

            if self.limit > 0:
                limit_patterns = [
                    (r"CRAWL_LIMIT\s*=\s*\d+", f"CRAWL_LIMIT = {self.limit}"),
                    (r"crawl_limit\s*=\s*\d+", f"crawl_limit = {self.limit}"),
                ]
                for pattern, replacement in limit_patterns:
                    if re.search(pattern, content):
                        content = re.sub(pattern, replacement, content)
                        modified = True

            if modified:
                with open(config_file, "w", encoding="utf-8") as f:
                    f.write(content)
                return True
            return False

        except Exception as e:
            print(f"   ⚠️ 配置更新异常: {e}")
            return False

    def _platform_mapping(self) -> str:
        mapping = {
            "xiaohongshu": "xhs",
            "xhs": "xhs",
            "zhihu": "zhihu",
        }
        return mapping.get(self.platform, self.platform)

    def _copy_data(self) -> None:
        if not self.data_dir.exists():
            print(f"   ⚠️ 数据目录不存在: {self.data_dir}")
            return

        self.target_data_dir.mkdir(parents=True, exist_ok=True)
        copied_count = 0
        data_extensions = {".json", ".jsonl", ".csv", ".txt"}

        for filepath in self.data_dir.rglob("*"):
            if filepath.is_file() and filepath.suffix in data_extensions:
                rel_path = filepath.relative_to(self.data_dir)
                dest_path = self.target_data_dir / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                try:
                    shutil.copy2(filepath, dest_path)
                    copied_count += 1
                    if copied_count <= 10:
                        print(f"   📂 复制: {rel_path}")
                except Exception as e:
                    print(f"   ⚠️ 复制失败: {rel_path} - {e}")

        print(f"   📊 复制了 {copied_count} 个数据文件")