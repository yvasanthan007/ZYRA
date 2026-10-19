"Regression coverage for voice phishing summaries and risk-score semantics."""
import unittest
from backend.url_analyzer.analyzer import build_voice_summary
class VoicePhishingSummaryTests(unittest.TestCase):
    def test_summary_states_safety_score_and_phishing_probability_distinctly(self):
        summary = build_voice_summary({
            "success": True,
            "score": 15,
            "risk_level_label": "CRITICAL",
            "classification": "MALICIOUS",
            "domain_display": "login-example.test",
            "ml_phishing": {"available": True, "probability": 0.94},
        })
        self.assertIn("Safety score: 15 out of 100", summary)
        self.assertIn("risk level: critical", summary)
        self.assertIn("94 percent phishing probability", summary)
        self.assertIn("Do not open", summary)

    def test_safe_summary_does_not_mislabel_safety_score_as_risk(self):
        summary = build_voice_summary({
            "success": True,
            "score": 88,
            "risk_level_label": "LOW",
            "classification": "LIKELY_SAFE",
            "domain_display": "example.test",
            "ml_phishing": {"available": True, "probability": 0.03},
        })
        self.assertIn("Safety score: 88 out of 100", summary)
        self.assertIn("risk level: low", summary)
        self.assertIn("3 percent phishing probability", summary)
        self.assertNotIn("high risk", summary)

if __name__ == "__main__":
    unittest.main()
