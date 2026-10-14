"""Regression: selected/entered URL reaches the detector directly."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "desktop-ui"))

import bridge_server
import screen_ocr
from unittest.mock import patch
from backend.zyra_bridge import _link_capture_report
class AnalyzeLinkTests(unittest.TestCase):
    def test_ocr_prefers_address_bar_before_page_content(self):
        class FakeImage:
            size = (1600, 900)

            def crop(self, _box):
                return self
        with patch("screen_ocr.extract_text_from_image", side_effect=[
            "https://phish-example.xyz/login", "https://other-page-link.com"
        ]) as ocr:
            urls = screen_ocr.extract_urls_from_image(FakeImage())
        self.assertEqual(urls, ["https://phish-example.xyz/login"])
        self.assertEqual(ocr.call_count, 1)

    def test_ocr_finds_split_domain_and_path(self):
        self.assertEqual(
            screen_ocr.extract_urls_from_text("https:// secure-login . xyz / verify"),
            ["https://secure-login.xyz/verify"],
        )

    def test_screen_url_takes_priority_over_stale_clipboard_url(self):
        with patch.object(screen_ocr, "_capture_url_isolated",
                          return_value="https://screen-example.xyz/login"), \
             patch.object(screen_ocr, "_clipboard_exact_url",
                          return_value="https://stale-clipboard.com"):
            self.assertEqual(
                screen_ocr.get_active_url(),
                "https://screen-example.xyz/login",
            )

    def test_request_to_check_screen_link_does_not_use_unrelated_text_url(self):
        with patch("screen_ocr.get_active_url",
                   return_value="https://screen-example.xyz/login"), \
             patch("backend.zyra_bridge.analyze_url_security",
                   return_value={"verdict": "PHISHING DETECTED"}) as analyze, \
             patch("backend.zyra_bridge.format_security_report",
                   return_value="Verdict: PHISHING DETECTED"):
            report, url = _link_capture_report(
                "Analyze the link on the screen, not this pasted URL: "
                "https://unrelated.example.com"
            )
        self.assertEqual(url, "https://screen-example.xyz/login")
        self.assertIn("PHISHING", report)
        analyze.assert_called_once_with("https://screen-example.xyz/login")

class AnalyzeLinkTestsLegacy(unittest.TestCase):
    def test_selected_url_analyzed_directly(self):
        res = bridge_server.handle_message(
            {"type": "analyze_link",
             "data": "https://example.com/login"})
        self.assertTrue(res["success"], res)
        self.assertEqual(res["data"]["url"], "https://example.com/login")
        self.assertEqual(res["data"]["source"], "selected")
        self.assertIn("verdict", res["data"])

    def test_dict_url_with_timeout(self):
        res = bridge_server.handle_message(
            {"type": "analyze_link",
             "data": {"url": "https://example.com/", "timeout_secs": 3}})
        self.assertTrue(res["success"], res)
        self.assertEqual(res["data"]["source"], "selected")

    def test_missing_url_reports_clearly(self):
        res = bridge_server.handle_message(
            {"type": "analyze_link",
             "data": {"url": "   ", "timeout_secs": 2}})
        # No explicit URL -> bounded capture fallback; empty clipboard and
        # no screen URL must report missing-URL, never fake a result.
        self.assertIn(res.get("source", "none"), ("none",))
        self.assertFalse(res["success"])
        self.assertIn("No URL", res.get("error", ""))

    def test_ocr_timeout_does_not_hang(self):
        import screen_ocr
        orig = screen_ocr.get_active_url
        screen_ocr.get_active_url = lambda: (_ for _ in ()).throw(
            TimeoutError("slow"))
        try:
            import concurrent.futures as fut
            # Simulate the bridge's bounded capture directly.
            with fut.ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(fut.TimeoutError):
                    pool.submit(screen_ocr.get_active_url).result(timeout=0.2)
        finally:
            screen_ocr.get_active_url = orig

    def test_voice_available_after_scan(self):
        ok = bridge_server.handle_message(
            {"type": "analyze_link",
             "data": "https://example.com/"})
        self.assertTrue(ok["success"], ok)
        status = bridge_server.handle_message({"type": "voice_status"})
        self.assertTrue(status["success"])
        stop = bridge_server.handle_message(
            {"type": "voice_toggle", "data": False})
        self.assertTrue(stop["success"])
        fail = bridge_server.handle_message(
            {"type": "analyze_link", "data": {"url": "", "timeout_secs": 2}})
        self.assertFalse(fail["success"])
        status2 = bridge_server.handle_message({"type": "voice_status"})
        self.assertTrue(status2["success"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
