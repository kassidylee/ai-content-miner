import unittest

from scripts.setup_twscrape_session import _cookie_string


class SetupTwscrapeSessionTest(unittest.TestCase):
    def test_cookie_string_contains_both_required_browser_cookies(self):
        value = _cookie_string("token-value", "csrf-value")

        self.assertEqual(value, "auth_token=token-value; ct0=csrf-value")

    def test_cookie_string_rejects_empty_or_delimiter_values(self):
        for auth_token, ct0 in (("", "csrf"), ("token", ""), ("bad;value", "csrf")):
            with self.subTest(auth_token=auth_token, ct0=ct0):
                with self.assertRaises(ValueError):
                    _cookie_string(auth_token, ct0)


if __name__ == "__main__":
    unittest.main()
