"""
Regression tests: URL analysis intent detection (backend/url_analyzer/intent).

Key behaviour: a standalone URL pasted on its own is an implicit analysis
request — no verb or noun required: 'https://example.com:8443/login' must
activate the URL analyzer.
"""

import unittest

from backend.url_analyzer.intent import (
    build_chat_ack,
    extract_target_url,
    is_url_analysis_intent,
)


class BareUrlIntentTests(unittest.TestCase):
    def test_synthetic_suspicious_standalone_url(self):
        self.assertTrue(
            is_url_analysis_intent(
                "https://login-verify-secure.xyz/update/account/password")
        )

    def test_standalone_url_with_port(self):
        self.assertTrue(is_url_analysis_intent("https://example.com:8443/login"))

    def test_standalone_url_with_trailing_punctuation(self):
        self.assertTrue(is_url_analysis_intent("https://example.com/path."))

    def test_www_standalone_url(self):
        self.assertTrue(is_url_analysis_intent("www.example.com/deal"))

    def test_url_with_verb_and_safety_question(self):
        self.assertTrue(is_url_analysis_intent("check https://example.com for phishing"))
        self.assertTrue(is_url_analysis_intent("Is https://example.com safe?"))
        self.assertTrue(is_url_analysis_intent("Analyze https://example.com"))

    def test_no_url_explicit_phrase_asks_for_url(self):
        self.assertTrue(is_url_analysis_intent("check this url for phishing"))
        ack = build_chat_ack(None)
        self.assertIn("provide the URL", ack)

    def test_plain_chat_is_not_intent(self):
        self.assertFalse(is_url_analysis_intent("what's the weather today"))
        self.assertFalse(is_url_analysis_intent(""))
        self.assertFalse(is_url_analysis_intent(None))

    def test_extract_target_url(self):
        self.assertEqual(
            extract_target_url("Analyze https://example.com now"),
            "https://example.com",
        )
        self.assertIsNone(extract_target_url("no link here"))


if __name__ == "__main__":
    unittest.main()
