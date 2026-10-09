"""P1 regression: dangerous protocols + SSRF guards + URL shapes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.url_analyzer.validator import validate_url


class DangerousProtocolTests(unittest.TestCase):
    def test_javascript_rejected_as_dangerous_protocol(self):
        result = validate_url("javascript:alert(1)")
        self.assertFalse(result["valid"])
        self.assertEqual(result["error_code"], "DANGEROUS_PROTOCOL")

    def test_other_dangerous_schemes_rejected(self):
        for raw in ("data:text/html,hi", "file:///etc/passwd",
                    "vbscript:msgbox(1)", "ftp://example.com/x"):
            with self.subTest(raw=raw):
                result = validate_url(raw)
                self.assertFalse(result["valid"])
                self.assertEqual(result["error_code"], "DANGEROUS_PROTOCOL")

    def test_ssrf_guards_intact(self):
        blocked = validate_url("http://localhost/test")
        self.assertFalse(blocked["valid"])
        self.assertEqual(blocked["error_code"], "BLOCKED_TARGET")
        invalid = validate_url("not a valid URL")
        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["error_code"], "INVALID_URL")

    def test_valid_urls_preserve_full_shape(self):
        cases = [
            ("https://example.com/", 443, "/", None),
            ("https://example.com/login?next=%2Faccount",
             443, "/login", "next=%2Faccount"),
            ("https://example.com:8443/login", 8443, "/login", None),
        ]
        for raw, port, path, query in cases:
            with self.subTest(raw=raw):
                result = validate_url(raw)
                self.assertTrue(result["valid"], result)
                self.assertEqual(result["normalized_url"], raw)
                self.assertEqual(result["port"], port)
                self.assertEqual(result["path"], path)
                self.assertEqual(result["query"], query)


if __name__ == "__main__":
    unittest.main(verbosity=2)
