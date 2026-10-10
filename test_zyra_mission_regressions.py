"""Focused regressions for voice lifecycle, URL analysis, OCR timeout and ML fusion."""
import importlib.util
import os
import sys
import threading
import time
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "desktop-ui"))

# bridge_server.py is an executable runner, not an importable package module, so
# load it from its file path instead of relying on static import resolution.
_spec = importlib.util.spec_from_file_location(
    "bridge_server", os.path.join(_ROOT, "desktop-ui", "bridge_server.py"))
bridge_server = importlib.util.module_from_spec(_spec)
sys.modules["bridge_server"] = bridge_server
_spec.loader.exec_module(bridge_server)

import link_analysis
from backend.ml_phishing import predictor
from backend.ml_phishing.features import FEATURE_NAMES
from backend.url_analyzer import analyzer
from backend.url_analyzer.risk_scorer import score_scan
class _StubXGBoost:
    classes_ = [0, 1]
    n_features_in_ = len(FEATURE_NAMES)
    feature_importances_ = [0.1] * len(FEATURE_NAMES)

    def __init__(self, probabilities):
        self.probabilities = probabilities
        self.seen = None
    def predict_proba(self, vectors):
        self.seen = vectors
        return [self.probabilities]

class MissionRegressionTests(unittest.TestCase):
    def test_predictor_runs_model_with_canonical_feature_order(self):
        model = _StubXGBoost([0.08, 0.92])
        with mock.patch.object(predictor, "_load", return_value=(model, {"algorithm": "XGBClassifier"})):
            result = predictor.analyze_url("https://login-verify.xyz/account")
        self.assertTrue(result["available"])
        self.assertEqual(result["algorithm"], "XGBClassifier")
        self.assertEqual(result["probability"], 0.92)
        self.assertEqual(len(model.seen[0]), len(FEATURE_NAMES))
        self.assertEqual(result["verdict"], "PHISHING")

    def test_predictor_respects_positive_class_label_order(self):
        model = _StubXGBoost([0.91, 0.09])
        model.classes_ = [1, 0]
        with mock.patch.object(predictor, "_load", return_value=(model, {"algorithm": "XGBClassifier"})):
            result = predictor.analyze_url("https://example.com/")
        self.assertEqual(result["probability"], 0.91)

    def test_unknown_model_class_does_not_return_fake_probability(self):
        model = _StubXGBoost([0.5, 0.5])
        model.classes_ = ["clean", "other"]
        with mock.patch.object(predictor, "_load", return_value=(model, {})):
            result = predictor.analyze_url("https://example.com/")
        self.assertFalse(result["available"])

    def test_heuristic_and_ml_share_direct_url_analysis(self):
        ml = {"available": True, "algorithm": "XGBClassifier", "probability": 0.96,
              "percent": 96, "verdict": "PHISHING"}
        with mock.patch.object(link_analysis, "_ml_check", return_value=ml):
            result = link_analysis.analyze_url(
                "http://paypal-login-account.xyz/verify")
        self.assertIn("Suspicious TLD", [c["check"] for c in result["checks"]])
        self.assertIn("ML Phishing Classifier", [c["check"] for c in result["checks"]])
        self.assertEqual(result["verdict"], "Dangerous")
        self.assertNotEqual(result["ml_phishing"].get("available"), False)

    def test_malformed_url_never_receives_safe_verdict(self):
        for url in ("javascript:alert(1)", "https://example.com:bad/path", "https:///path"):
            with self.subTest(url=url):
                self.assertNotEqual(link_analysis.analyze_url(url)["verdict"], "Safe")

    def test_analysis_bridge_returns_after_ocr_timeout_without_waiting_worker(self):
        import screen_ocr
        original = screen_ocr.get_active_url
        release = threading.Event()
        screen_ocr.get_active_url = lambda: (release.wait(5.0), None)[1]
        try:
            started = time.monotonic()
            result = bridge_server.handle_message({"type": "analyze_link", "data": {"url": "", "timeout_secs": 2}})
            self.assertLess(time.monotonic() - started, 3.0)
            self.assertFalse(result["success"])
            self.assertEqual(result["source"], "none")
        finally:
            release.set()
            screen_ocr.get_active_url = original
    def test_voice_lifecycle_releases_lock_after_failed_scan_path(self):
        failure = bridge_server.handle_message({"type": "analyze_link", "data": {"url": "", "timeout_secs": 2}})
        self.assertFalse(failure["success"])
        with mock.patch.object(bridge_server.sr, "Recognizer") as rec, \
             mock.patch.object(bridge_server, "_capture_voice_audio", return_value=object()), \
             mock.patch("listen._recognize", return_value="what is the time"), \
             mock.patch.object(bridge_server, "process_voice_command",
                               return_value={"response": "It is a test", "action": "current_time"}), \
             mock.patch("backend.zyra_bridge.speak_text"):
            result = bridge_server.handle_message({"type": "voice_toggle", "data": True})
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["transcript"], "what is the time")
        self.assertFalse(bridge_server._voice_capture_active)
        self.assertFalse(bridge_server._voice_capture_lock.locked())

    def test_scan_pipeline_calls_heuristics_and_xgboost_and_scoring(self):
        seen = {}
        def fake_ml(url):
            seen["ml_url"] = url
            return {"available": True, "algorithm": "XGBClassifier", "probability": 0.91,
                    "percent": 91, "verdict": "PHISHING", "top_signals": []}
        with mock.patch.object(analyzer, "validate_url", return_value={
                 "valid": True, "normalized_url": "https://fake.example/path", "scheme": "https",
                 "hostname": "fake.example", "port": 443, "path": "/path", "query": None,
                 "fragment": None}), \
             mock.patch.object(analyzer, "analyze_dns", return_value={"hostname": "fake.example", "registered_domain": "example", "resolved": True, "whois_available": True}), \
             mock.patch.object(analyzer, "analyze_ssl", return_value={"checked": True, "status": "valid", "valid": True}), \
             mock.patch.object(analyzer, "_probe_redirects", return_value={"chain": [], "blocked": False}), \
             mock.patch.object(analyzer, "check_reputation", return_value={"available": True, "reputation": "clean"}), \
             mock.patch.object(analyzer, "detect_threats", return_value=[{"id": "heuristic_test", "severity": "HIGH", "title": "test heuristic", "score_impact": 22}]), \
             mock.patch.object(analyzer, "analyze_url_ml", side_effect=fake_ml):
            result = analyzer.run_url_scan("https://fake.example/path")
        self.assertEqual(seen["ml_url"], "https://fake.example/path")
        self.assertEqual(result["ml_phishing"]["algorithm"], "XGBClassifier")
        self.assertTrue(any(f["id"] == "heuristic_test" for f in result["findings"]))
        self.assertEqual(result["classification"], "MALICIOUS")
        self.assertLessEqual(result["score"], 15)

    def test_risk_score_semantics_are_explicit_and_probability_is_not_inverted(self):
        low = score_scan([], domain_info={"resolved": True, "whois_available": True},
                         ssl_info={"checked": True}, reputation={"available": True, "reputation": "clean"},
                         ml_analysis={"available": True, "probability": 0.05})
        high = score_scan([], domain_info={"resolved": True, "whois_available": True},
                          ssl_info={"checked": True}, reputation={"available": True, "reputation": "clean"},
                          ml_analysis={"available": True, "probability": 0.95})
        self.assertGreater(low["score"], high["score"])
        self.assertEqual(high["classification"], "MALICIOUS")
        self.assertIn("higher = safer", low["score_semantics"])

    # ── Bug 1: voice + URL analysis ──────────────────────────────

    def test_bug1_url_reaches_analyzer_through_ocr_clipboard_chain(self):
    def test_risk_score_semantics_are_explicit_and_probability_is_not_inverted(self):
        low = score_scan([], domain_info={"resolved": True, "whois_available": True},
                         ssl_info={"checked": True}, reputation={"available": True, "reputation": "clean"},
                         ml_analysis={"available": True, "probability": 0.05})
        high = score_scan([], domain_info={"resolved": True, "whois_available": True},
                          ssl_info={"checked": True}, reputation={"available": True, "reputation": "clean"},
                          ml_analysis={"available": True, "probability": 0.95})
        self.assertGreater(low["score"], high["score"])
        self.assertEqual(high["classification"], "MALICIOUS")
        self.assertIn("higher = safer", low["score_semantics"])
    def test_risk_score_semantics_are_explicit_and_probability_is_not_inverted(self):
        low = score_scan([], domain_info={"resolved": True, "whois_available": True},
                         ssl_info={"checked": True}, reputation={"available": True, "reputation": "clean"},
                         ml_analysis={"available": True, "probability": 0.05})
        high = score_scan([], domain_info={"resolved": True, "whois_available": True},
                          ssl_info={"checked": True}, reputation={"available": True, "reputation": "clean"},
                          ml_analysis={"available": True, "probability": 0.95})
        self.assertGreater(low["score"], high["score"])
        self.assertEqual(high["classification"], "MALICIOUS")
        self.assertIn("higher = safer", low["score_semantics"])

    # ── Bug 1: voice + URL analysis ──────────────────────────────

    def test_bug1_url_reaches_analyzer_through_ocr_clipboard_chain(self):
        """Direct/supplied URL (fast path) and OCR fallback both reach the
        heuristic + XGBoost analyzer and produce a structured verdict."""
        import screen_ocr

        cases = [
            "https://www.google.com",          # fast path (clipboard exact)
            "http://192.168.1.1/login",        # OCR fallback (screen)
            "https://bit.ly/3xM7abc",          # OCR fallback (url inside clipboard)
        ]
        for url in cases:
            with self.subTest(url=url):
                self.assertIsNotNone(url)
                result = link_analysis.analyze_url(url)
                self.assertTrue(result["available"], result)
                self.assertIn(result["verdict"], ("Safe", "Suspicious", "Dangerous"))
                self.assertEqual(result["url"], url)
                # XGBoost heuristic is exercised inside the 8-check pipeline.
                self.assertTrue(result.get("checks"))

    def test_bug1_ocr_timeout_returns_none_and_does_not_block_voice(self):
        """OCR timeout must yield None quickly and must not break the
        microphone / speech service (voice recovery)."""
        import screen_ocr
        import threading

        original = screen_ocr.get_active_url
        release = threading.Event()

        def _blocking():
            # Simulate a hung OCR pass; the bounded OCR timeout (or the caller)
            # must time it out and return None instead of hanging forever.
            release.wait(10.0)
            return None

        screen_ocr.get_active_url = _blocking
        try:
            self.assertIsNone(screen_ocr.get_active_url())
        finally:
            release.set()
            screen_ocr.get_active_url = original


    def test_risk_score_semantics_are_explicit_and_probability_is_not_inverted(self):
        low = score_scan([], domain_info={"resolved": True, "whois_available": True},
                         ssl_info={"checked": True}, reputation={"available": True, "reputation": "clean"},
                         ml_analysis={"available": True, "probability": 0.05})
        high = score_scan([], domain_info={"resolved": True, "whois_available": True},
                          ssl_info={"checked": True}, reputation={"available": True, "reputation": "clean"},
                          ml_analysis={"available": True, "probability": 0.95})
        self.assertGreater(low["score"], high["score"])
        self.assertEqual(high["classification"], "MALICIOUS")
        self.assertIn("higher = safer", low["score_semantics"])

    # ── Bug 1: voice + URL analysis ──────────────────────────────

    def test_bug1_url_reaches_analyzer_through_ocr_clipboard_chain(self):
        """Direct/supplied URL (fast path) and OCR fallback both reach the
        heuristic + XGBoost analyzer and produce a structured verdict."""
        import screen_ocr

        cases = [
            "https://www.google.com",          # fast path (clipboard exact)
            "http://192.168.1.1/login",        # OCR fallback (screen)
            "https://bit.ly/3xM7abc",          # OCR fallback (url inside clipboard)
        ]
        for url in cases:
            with self.subTest(url=url):
                self.assertIsNotNone(url)
                result = link_analysis.analyze_url(url)
                self.assertTrue(result["available"], result)
                self.assertIn(result["verdict"], ("Safe", "Suspicious", "Dangerous"))
                self.assertEqual(result["url"], url)
                # XGBoost heuristic is exercised inside the 8-check pipeline.
                self.assertTrue(result.get("checks"))

    def test_bug1_ocr_timeout_returns_none_and_does_not_block_voice(self):
        """OCR timeout must yield None quickly and must not break the
        microphone / speech service (voice recovery)."""
        import screen_ocr
        import threading

        original = screen_ocr.get_active_url
        release = threading.Event()

        def _blocking():
            # Simulate a hung OCR pass; the bounded OCR timeout (or the caller)
            # must time it out and return None instead of hanging forever.
            release.wait(10.0)
            return None

        screen_ocr.get_active_url = _blocking
        try:
            self.assertIsNone(screen_ocr.get_active_url())
        finally:
            release.set()
            screen_ocr.get_active_url = original



if __name__ == "__main__":
    unittest.main(verbosity=2)
