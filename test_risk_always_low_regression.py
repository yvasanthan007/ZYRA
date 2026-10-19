"Regression tests: model phishing probability must never display as LOW risk."""
import unittest
from unittest.mock import patch
from backend.url_analyzer.risk_scorer import score_scan
from backend.link_security import analyze_url_security
from link_analysis import analyze_url
class RiskProbabilityDisplayTests(unittest.TestCase):
    def test_probability_band_not_low_for_elevated_phishing(self):
        expectations = ((0.10, "LOW"), (0.55, "MEDIUM"), (0.78, "HIGH"), (0.95, "CRITICAL"))
        for probability, level in expectations:
            with self.subTest(probability=probability):
                result = score_scan(
                    [], domain_info={"resolved": True, "whois_available": True},
                    ssl_info={"checked": True},
                    reputation={"available": True, "reputation": "clean"},
                    ml_analysis={"available": True, "probability": probability},
                )
                self.assertEqual(result["phishing_risk_level"], level)
                if probability >= 0.55:
                    self.assertNotEqual(result["risk_level"], "LOW")

    def test_link_security_ml_84_percent_maps_to_high_risk(self):
        with patch("backend.link_security._ml_assessment", return_value={
            "available": True, "probability": 0.84, "algorithm": "XGBClassifier",
            "verdict": "LIKELY_PHISHING",
        }):
            result = analyze_url_security("https://verify-account.example/login")
        self.assertEqual(result["risk_score"], "High")
        self.assertEqual(result["risk_score_0_100"], 84.0)
        self.assertEqual(result["safety_score"], 16)

    def test_legacy_link_analysis_uses_ml_probability_as_public_risk_score(self):
        with patch("link_analysis._ml_check", return_value={
            "available": True, "probability": 0.84, "algorithm": "XGBClassifier",
            "verdict": "LIKELY_PHISHING",
        }):
            result = analyze_url("https://verify-account.example/login")
        self.assertGreaterEqual(result["score"], 84)
        self.assertEqual(result["verdict"], "Dangerous")

if __name__ == "__main__":
    unittest.main()
