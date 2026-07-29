import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from notifier.twitter_wecom import send_twitter_wecom


def make_item(index):
    return {
        "title": f"Title {index}",
        "abstract": f"Abstract {index}",
        "source_url": f"https://x.com/user/status/{index}",
    }


class TwitterWeComTest(unittest.TestCase):
    def test_notification_uses_single_daily_list_and_limit(self):
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {"errcode": 0},
        )
        requests = SimpleNamespace(
            RequestException=Exception,
            post=MagicMock(return_value=response),
        )
        with patch.dict(sys.modules, {"requests": requests}), patch(
            "notifier.twitter_wecom.config.TWITTER_ENABLE_WECOM",
            True,
        ), patch(
            "notifier.twitter_wecom.config.WECOM_WEBHOOK",
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        ), patch(
            "notifier.twitter_wecom.config.TWITTER_DAILY_LIMIT",
            8,
        ):
            sent = send_twitter_wecom(
                [make_item(index) for index in range(1, 10)]
            )

        self.assertTrue(sent)
        payload = requests.post.call_args.kwargs["json"]
        content = payload["markdown_v2"]["content"]
        self.assertIn("今日精选：8 条", content)
        self.assertIn("**8. Title 8**", content)
        self.assertNotIn("Title 9", content)
        self.assertNotIn("页面另有", content)


if __name__ == "__main__":
    unittest.main()
