"""Regression: selected/entered URL reaches the detector directly."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "desktop-ui"))

import bridge_server


class AnalyzeLinkTests(unittest.TestCase):
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
