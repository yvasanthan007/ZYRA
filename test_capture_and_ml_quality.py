"Regressions for active-screen URL capture and phishing risk scoring."""
import unittest
from unittest.mock import patch
import screen_ocr
from backend.url_analyzer.risk_scorer import score_scan
class ActiveBrowserCaptureTests(unittest.TestCase):
    def test_browser_address_bar_fallback_selected_only_for_browser_foreground(self):
        with patch("screen_ocr.sys.platform", "win32"), \
             patch("win32gui.GetForegroundWindow", return_value=123), \
             patch("win32gui.GetWindowText", return_value="Suspicious Page - Google Chrome"), \
             patch("pyperclip.paste", side_effect=["keep this clipboard", "https://evil.test/login"]), \
             patch("pyperclip.copy") as copy, \
             patch("pyautogui.hotkey"), \
             patch("screen_ocr.time.sleep"):
            self.assertEqual(screen_ocr._get_active_browser_url(), "https://evil.test/login")
        copy.assert_called_once_with("keep this clipboard")

    def test_non_browser_foreground_is_not_read_as_browser_url(self):
        with patch("screen_ocr.sys.platform", "win32"), \
             patch("win32gui.GetForegroundWindow", return_value=123), \
             patch("win32gui.GetWindowText", return_value="ZYRA"), \
             patch("pyperclip.paste") as paste:
            self.assertIsNone(screen_ocr._get_active_browser_url())
        paste.assert_not_called()

    def test_browser_url_is_tried_before_stale_clipboard(self):
        with patch.object(screen_ocr, "_capture_url_isolated", return_value=None), \
             patch.object(screen_ocr, "_get_active_browser_url", return_value="https://active.test/login"), \
             patch.object(screen_ocr, "_clipboard_exact_url") as clipboard:
            self.assertEqual(screen_ocr.get_active_url(), "https://active.test/login")
        clipboard.assert_not_called()

class ModelRiskFloorTests(unittest.TestCase):
    def test_elevated_ml_probability_lowers_safety_score_even_if_network_clean(self):
        scored = score_scan(
            [], domain_info={"resolved": True, "whois_available": True},
            ssl_info={"checked": True},
            reputation={"available": True, "reputation": "clean"},
            ml_analysis={"available": True, "probability": 0.78, "algorithm": "XGBClassifier"},
        )
        self.assertEqual(scored["classification"], "SUSPICIOUS")
        self.assertEqual(scored["score"], 22)
        self.assertEqual(scored["risk_level"], "CRITICAL")

    def test_extreme_probability_is_malicious_and_safety_score_critical(self):
        scored = score_scan([], ml_analysis={"available": True, "probability": 0.96})
        self.assertEqual(scored["classification"], "MALICIOUS")
        self.assertLessEqual(scored["score"], 15)
        self.assertEqual(scored["risk_level"], "CRITICAL")

    def test_predictor_flags_subtle_brand_impersonation_and_preserves_real_brand(self):
        from backend.ml_phishing.predictor import analyze_url
        phishing = analyze_url("https://g00gle.com/mail/u/0/")
        legitimate = analyze_url("https://accounts.google.com/signin")
        self.assertGreaterEqual(phishing["probability"], 0.75)
        self.assertLess(legitimate["probability"], 0.35)

    def test_invalid_probability_is_ignored_safely(self):
        scored = score_scan([], ml_analysis={"available": True, "probability": 4.2})
        self.assertEqual(scored["score"], 92)
        self.assertTrue(all("ML phishing classifier" not in item for item in scored["reasoning"]))

    def test_safety_score_is_inverse_of_phishing_probability(self):
        for probability in (0.10, 0.50, 0.80, 0.95):
            with self.subTest(probability=probability):
                scored = score_scan(
                    [], domain_info={"resolved": True, "whois_available": True},
                    ssl_info={"checked": True},
                    reputation={"available": True, "reputation": "clean"},
                    ml_analysis={"available": True, "probability": probability},
                )
                self.assertEqual(scored["score"], round((1 - probability) * 100))
                self.assertEqual(scored["phishing_probability"], probability)
                self.assertIn("at most", scored["score_semantics"])

if __name__ == "__main__":
    unittest.main()
