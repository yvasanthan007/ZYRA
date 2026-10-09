"""P2 regression: shortener uncertainty + ML/safety distinction (no retrain)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.ml_phishing.predictor import analyze_url_ml
from backend.url_analyzer.risk_scorer import score_scan

SHORTENER_FINDING = {
    "id": "url_shortener", "severity": "MEDIUM",
    "category": "obfuscation",
    "title": "URL shortener masks the destination",
    "detail": "short", "score_impact": 12, "positive": False,
}


class MlReliabilityGuardTests(unittest.TestCase):
    def test_shortener_low_ml_no_reputation_is_unknown(self):
        scored = score_scan(
            [dict(SHORTENER_FINDING)],
            ml_analysis={"available": True, "probability": 0.0,
                         "algorithm": "RandomForestClassifier"})
        self.assertEqual(scored["classification"], "UNKNOWN")
        self.assertTrue(any("shortener" in line.lower()
                            for line in scored["reasoning"]))

    def test_shortener_high_ml_still_malicious(self):
        scored = score_scan(
            [dict(SHORTENER_FINDING)],
            ml_analysis={"available": True, "probability": 0.95,
                         "algorithm": "RandomForestClassifier"})
        self.assertEqual(scored["classification"], "MALICIOUS")

    def test_benign_login_query_and_port_shapes(self):
        benign = analyze_url_ml("https://example.com/login?next=%2Faccount")
        self.assertTrue(benign["available"])
        self.assertLess(benign["probability"], 0.55)
        port = analyze_url_ml("https://example.com:8443/login")
        self.assertTrue(port["available"])
        self.assertEqual(port["risk_band"], "LOW")

    def test_suspicious_tld_ip_and_malformed_inputs(self):
        phish = analyze_url_ml(
            "http://paypa1-secure-login.verify-account-now.xyz/login.php")
        self.assertTrue(phish["available"])
        self.assertGreaterEqual(phish["probability"], 0.60)
        ip = analyze_url_ml("http://192.0.2.44/paypal/login.php")
        self.assertTrue(ip["available"])
        self.assertGreaterEqual(ip["probability"], 0.60)
        for bad in (None, "", "   ", "not a url"):
            result = analyze_url_ml(bad)
            self.assertIsInstance(result, dict)
            self.assertIn("available", result)

    def test_ml_probability_and_safety_score_not_confused(self):
        ml = analyze_url_ml("https://example.com/")
        fused = score_scan([])
        self.assertIn(ml["risk_band"],
                      ("CRITICAL", "HIGH", "MEDIUM", "LOW"))
        self.assertIn(fused["risk_level"],
                      ("CRITICAL", "HIGH", "MEDIUM", "LOW"))
        self.assertEqual(fused["score_semantics"],
                         "safety: higher score = safer = lower risk")


if __name__ == "__main__":
    unittest.main(verbosity=2)
