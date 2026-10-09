"""P1 regression: standalone http(s) URLs trigger URL-analysis intent."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.url_analyzer.intent import (
    extract_target_url,
    is_url_analysis_intent,
)
from backend.url_analyzer.validator import validate_url


class BareUrlIntentTests(unittest.TestCase):
    def test_standalone_urls_trigger_intent(self):
        for raw in ("https://example.com/",
                    "https://example.com/login?next=%2Faccount",
                    "https://example.com:8443/login"):
            with self.subTest(raw=raw):
                self.assertTrue(is_url_analysis_intent(raw))
                self.assertEqual(extract_target_url(raw), raw)

    def test_synthetic_suspicious_standalone_url(self):
        raw = "http://paypa1-secure-login.verify-account-now.example/login"
        self.assertTrue(is_url_analysis_intent(raw))
        self.assertEqual(extract_target_url(raw), raw)

    def test_explicit_request_with_port_url(self):
        text = "please analyze https://example.com:8443/login"
        self.assertTrue(is_url_analysis_intent(text))
        self.assertEqual(extract_target_url(text),
                         "https://example.com:8443/login")

    def test_no_url_request_asks_for_url(self):
        self.assertTrue(is_url_analysis_intent("check this link"))
        self.assertIsNone(extract_target_url("check this link"))

    def test_non_urls_stay_non_intent(self):
        # NOTE: "example.com is a nice site" contains a bare domain AND the
        # noun "site", so the pre-existing noun rule fires (unchanged by the
        # standalone-URL fix, which only adds scheme-prefixed auto-intent).
        for raw in ("not a valid URL", "", "hello zyra how are you",
                    "example.com"):
            with self.subTest(raw=raw):
                self.assertFalse(is_url_analysis_intent(raw))

    def test_dangerous_inputs_never_auto_trigger(self):
        self.assertFalse(is_url_analysis_intent("javascript:alert(1)"))
        self.assertFalse(
            is_url_analysis_intent("saw http://localhost/test yesterday"))
        self.assertFalse(validate_url("http://localhost/test")["valid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
