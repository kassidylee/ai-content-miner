import unittest
from types import SimpleNamespace
from unittest.mock import patch

from notifier.wecom import (
    MAX_MESSAGE_BYTES,
    build_markdown,
    send_markdown_v2,
    validate_config,
)


def make_item(index=1):
    return {
        "title": f"Agent [release] {index}",
        "abstract": "A concise summary.",
        "platform": "x",
        "source_url": f"https://x.com/user/status/{index}",
        "_output_path": f"reports/legacy-{index}.html",
    }


class WecomTest(unittest.TestCase):
    def test_message_links_to_source_instead_of_legacy_report(self):
        content = build_markdown([make_item()], platform="x")

        self.assertIn("https://x.com/user/status/1", content)
        self.assertNotIn("legacy-1.html", content)
        self.assertIn("https://", content)

    def test_message_respects_byte_limit(self):
        items = [make_item(index) for index in range(20)]
        for item in items:
            item["abstract"] = "摘要" * 800

        content = build_markdown(items, platform="x")

        self.assertLessEqual(len(content.encode("utf-8")), MAX_MESSAGE_BYTES)

    def test_config_rejects_placeholder_webhook(self):
        with patch(
            "notifier.wecom.config.WECOM_WEBHOOK",
            "https://example.com/hook",
        ):
            self.assertFalse(validate_config())

    def test_send_returns_wecom_result(self):
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {"errcode": 0},
        )
        with patch(
            "notifier.wecom.requests.post",
            return_value=response,
        ) as post:
            success = send_markdown_v2("test")

        self.assertTrue(success)
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
