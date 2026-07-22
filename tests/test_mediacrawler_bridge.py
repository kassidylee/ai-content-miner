import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler.mediacrawler_bridge import MediaCrawlerBridge


class MediaCrawlerBridgeTest(unittest.TestCase):
    def make_bridge(self, command_runner=subprocess.run):
        with patch(
            "crawler.mediacrawler_bridge.shutil.which",
            return_value="/usr/local/bin/uv",
        ):
            return MediaCrawlerBridge(command_runner=command_runner)

    def test_build_command_uses_real_upstream_flags(self):
        bridge = self.make_bridge()
        bridge.keywords = ["AI Agent", "大模型"]
        bridge.limit = 12

        command = bridge.build_command(Path("/tmp/current-run"))

        self.assertEqual(Path(command[0]).name, "uv")
        self.assertEqual(command[1:3], ["run", "main.py"])
        self.assertEqual(command[command.index("--keywords") + 1], "AI Agent,大模型")
        self.assertEqual(
            command[command.index("--crawler_max_notes_count") + 1], "12"
        )
        self.assertEqual(command[command.index("--save_data_option") + 1], "jsonl")
        self.assertEqual(command[command.index("--get_comment") + 1], "false")
        self.assertNotIn("--keyword", command)
        self.assertNotIn("--limit", command)

    def test_validate_rejects_commit_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir)
            for filename in ("main.py", "pyproject.toml", "uv.lock"):
                (base_path / filename).touch()

            bridge = self.make_bridge()
            bridge.base_path = base_path
            bridge.expected_commit = "expected-commit"
            with patch.object(bridge, "_read_actual_commit", return_value="other-commit"):
                errors = bridge.validate()

        self.assertTrue(any("版本不匹配" in error for error in errors))

    def test_zhihu_validation_requires_node_16_or_newer(self):
        bridge = self.make_bridge()
        bridge.platform = "zhihu"
        with patch(
            "crawler.mediacrawler_bridge.shutil.which", return_value=None
        ):
            error = bridge._node_runtime_error()

        self.assertIn("Node.js >=16", error)

    def test_nonzero_exit_is_failure(self):
        def failed_runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], returncode=7)

        bridge = self.make_bridge(command_runner=failed_runner)
        bridge.validate = lambda: []
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.target_data_dir = Path(temp_dir)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertEqual(result.returncode, 7)
        self.assertIn("退出码为 7", result.error)

    def test_zero_exit_without_content_is_failure(self):
        def empty_runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], returncode=0)

        bridge = self.make_bridge(command_runner=empty_runner)
        bridge.validate = lambda: []
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.target_data_dir = Path(temp_dir)
            result = bridge.run()

        self.assertFalse(result.success)
        self.assertEqual(result.returncode, 0)
        self.assertIn("没有产生内容数据", result.error)

    def test_run_returns_only_current_content_file(self):
        def successful_runner(command, **kwargs):
            output_dir = Path(command[command.index("--save_data_path") + 1])
            content_dir = output_dir / "xhs" / "jsonl"
            content_dir.mkdir(parents=True)
            (content_dir / "search_contents_2026-07-22.jsonl").write_text(
                '{"title": "本次内容"}\n', encoding="utf-8"
            )
            (content_dir / "search_comments_2026-07-22.jsonl").write_text(
                '{"content": "评论"}\n', encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, returncode=0)

        bridge = self.make_bridge(command_runner=successful_runner)
        bridge.validate = lambda: []
        bridge.platform = "xhs"
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge.target_data_dir = Path(temp_dir)
            historical = Path(temp_dir) / "historical.jsonl"
            historical.write_text('{"title": "历史内容"}\n', encoding="utf-8")
            result = bridge.run()

        self.assertTrue(result.success)
        self.assertEqual(len(result.data_files), 1)
        self.assertIn("search_contents_", result.data_files[0].name)


if __name__ == "__main__":
    unittest.main()
