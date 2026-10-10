"""
Regression tests: validator dangerous-protocol pre-check + SSRF guards.

Scheme-less dangerous input such as 'javascript:alert(1)' must be rejected
as DANGEROUS_PROTOCOL — NOT normalized into 'https://javascript:alert(1)'
and mis-reported as BAD_PORT. Legitimate URLs keep their full shape, and
the localhost/metadata hostname blocking must stay intact.
"""

import unittest

from backend.url_analyzer.validator import validate_url


class DangerousProtocolTests(unittest.TestCase):
    def test_javascript_rejected_as_dangerous_protocol(self):
        res = validate_url("javascript:alert(1)")
        self.assertFalse(res["valid"])
        self.assertEqual(res["error_code"], "DANGEROUS_PROTOCOL")

    def test_other_dangerous_schemes_rejected(self):
        dangerous = [
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "ftp://example.com/payload",
        ]
        for raw in dangerous:
            res = validate_url(raw)
            self.assertFalse(res["valid"], raw)
            self.assertEqual(res["error_code"], "DANGEROUS_PROTOCOL", raw)

    def test_ssrf_guards_intact(self):
        for raw in ("http://localhost/admin",
                    "http://metadata.google.internal/latest/meta-data/"):
            res = validate_url(raw)
            self.assertFalse(res["valid"], raw)
            self.assertEqual(res["error_code"], "BLOCKED_TARGET", raw)

    def test_valid_urls_preserve_full_shape(self):
        res = validate_url("https://example.com:8443/login?a=1#frag")
        self.assertTrue(res["valid"], res.get("error"))
        self.assertEqual(res["scheme"], "https")
        self.assertEqual(res["hostname"], "example.com")
        self.assertEqual(res["port"], 8443)
        self.assertEqual(res["path"], "/login")
        self.assertEqual(res["query"], "a=1")
        self.assertEqual(res["fragment"], "frag")
        self.assertTrue(
            str(res["normalized_url"]).startswith("https://example.com:8443/login")
        )

    def test_plain_http_url_still_allowed(self):
        res = validate_url("http://example.com/")
        self.assertTrue(res["valid"], res.get("error"))
        self.assertEqual(res["scheme"], "http")


if __name__ == "__main__":
    unittest.main()
