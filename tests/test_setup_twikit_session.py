import unittest

from scripts.setup_twikit_session import (
    KNOWN_TRANSACTION_ERROR,
    KNOWN_TRANSACTION_ISSUE_URL,
    _format_login_error,
)


class SetupTwikitSessionTest(unittest.TestCase):
    def test_known_transaction_error_explains_that_credentials_are_not_the_cause(self):
        message = _format_login_error(Exception(KNOWN_TRANSACTION_ERROR))

        self.assertIn("不代表凭证填写错误", message)
        self.assertIn("停止重复登录", message)
        self.assertIn(KNOWN_TRANSACTION_ISSUE_URL, message)

    def test_unknown_login_error_keeps_exception_context(self):
        message = _format_login_error(RuntimeError("network unavailable"))

        self.assertEqual(
            message,
            "登录失败：RuntimeError: network unavailable",
        )


if __name__ == "__main__":
    unittest.main()
