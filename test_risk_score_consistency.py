"Check model probability, score, risk band, classification and reports agree."""
import unittest
from unittest.mock import patch
from backend.link_security import analyze_url_security, format_security_report
from backend.url_analyzer.risk_scorer import score_scan
from backend.url_analyzer.report_generator import build_report_data, report_to_text
class RiskScoreConsistencyTests(unittest.TestCase):
    def test_phishing_probability_is_exposed_as_risk_and_inverse_safety(self):
        for probability in (0.1, 0.5, 0.78, 0.95):
            with self.subTest(probability=probability):
                result = score_scan(
                    [], domain_info={"resolved": True, "whois_available": True},
                    ssl_info={"checked": True},
                    reputation={"available": True, "reputation": "clean"},
                    ml_analysis={"available": True, "probability": probability},
                )
                self.assertEqual(result["risk_score"], probability * 100)
                self.assertLessEqual(result["score"], round((1-probability)*100))
                if probability >= 0.9:
                    self.assertEqual(result["classification"], "MALICIOUS")
                elif probability >= 0.75:
                    self.assertEqual(result["classification"], "SUSPICIOUS")
                elif probability >= 0.55:
                    self.assertEqual(result["classification"], "SUSPICIOUS")

    def test_link_security_report_does_not_hide_probability(self):
        ml = {"available": True, "probability": 0.84, "algorithm": "XGBClassifier", "verdict": "LIKELY_PHISHING"}
        with patch("backend.link_security._ml_assessment", return_value=ml):
            result = analyze_url_security("https://account-verify.example/login")
        self.assertEqual(result["risk_score_0_100"], 84.0)
        self.assertEqual(result["safety_score"], 16)
        text = format_security_report(result)
        self.assertIn("Phishing Probability: 84.0%", text)
        self.assertIn("Safety Score: 16 / 100", text)

    def test_detailed_report_labels_risk_vs_safety(self):
        result = {
            "success": True, "url": "https://example.test", "score": 16,
            "risk_score": 84.0, "phishing_probability": 0.84,
            "risk_level_label": "CRITICAL", "classification_label": "MALICIOUS",
            "classification_summary": "Malicious", "url_details": {}, "ssl": {},
            "domain": {}, "reputation": {}, "findings": [], "reasoning": [],
            "recommendation": "Do not open.",
        }
        text = report_to_text(build_report_data(result))
        self.assertIn("Safety Score:   16 / 100", text)
        self.assertIn("Phishing Probability: 84.0%", text)
        self.assertIn("Phishing Risk: 84.0 / 100", text)

if __name__ == "__main__":
    unittest.main()
