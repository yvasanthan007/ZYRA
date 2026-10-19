"Regression tests for phishing analysis quality and deterministic Zyra identity."""
import unittest
from unittest.mock import patch
from backend.ml_phishing.features import FEATURE_NAMES, extract_features
from backend.ml_phishing.predictor import analyze_url_ml, model_info
from backend.url_analyzer.threat_detector import detect_threats
from backend.zyra_bridge import process_chat, process_chat_stream
from screen_ocr import extract_urls_from_image
class ScreenUrlPriorityTests(unittest.TestCase):
    def test_address_bar_strip_wins_over_page_content_url(self):
        class FakeImage:
            size = (1600, 900)

            def crop(self, box):
                self.last_crop = box
                return self
        image = FakeImage()
        with patch("screen_ocr.extract_text_from_image", side_effect=[
            "https://actual-current-site.example.com/account",
            "https://ad-destination.example.net/offer",
        ]) as ocr:
            self.assertEqual(
                extract_urls_from_image(image),
                ["https://actual-current-site.example.com/account"],
            )
        self.assertEqual(ocr.call_count, 1)
        self.assertEqual(image.last_crop, (0, 0, 1600, 216))

class PhishingHeuristicTests(unittest.TestCase):
    def test_registered_domain_typosquat_is_a_feature(self):
        features = extract_features("https://paypa1.com/signin")
        self.assertIn("brand_typosquat", FEATURE_NAMES)
        self.assertEqual(features["brand_typosquat"], 1)

    def test_deep_threat_scan_flags_typosquat(self):
        findings = detect_threats(
            "https://paypa1.com/signin",
            {"hostname": "paypa1.com", "scheme": "https", "path": "/signin"},
            {"registered_domain": "paypa1.com", "resolved": True},
            {"status": "valid", "valid": True},
            {},
        )
        self.assertTrue(any(f["id"] == "typosquatting" for f in findings))

    def test_retrained_model_flags_typosquat_url(self):
        info = model_info()
        if not info.get("available"):
            self.skipTest(info.get("note", "trained model unavailable"))
        result = analyze_url_ml("https://paypa1.com/account/login")
        self.assertTrue(result.get("available"), result)
        self.assertGreaterEqual(result["probability"], 0.55, result)

class ZyraIdentityTests(unittest.TestCase):
    def test_chat_full_form_is_deterministic(self):
        expected = "ZYRA stands for Zero-latency Yielding Response Assistant."
        with patch("backend.zyra_bridge.ask_ai") as ask:
            self.assertEqual(process_chat("What is the full form of ZYRA?"), expected)
            ask.assert_not_called()

    def test_streamed_chat_full_form_is_static(self):
        result = process_chat_stream("What does ZYRA stand for?")
        self.assertEqual(result["kind"], "static")
        self.assertIn("Zero-latency Yielding Response Assistant", result["data"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
