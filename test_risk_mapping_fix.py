"""P0 regression: fused safety-score mapping (higher = safer = lower risk)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.url_analyzer.risk_scorer import _risk_level, score_scan


class SafetyRiskMappingTests(unittest.TestCase):
    def test_risk_level_boundaries(self):
        cases = [(0, "CRITICAL"), (24, "CRITICAL"), (25, "HIGH"),
                 (49, "HIGH"), (50, "MEDIUM"), (74, "MEDIUM"),
                 (75, "LOW"), (92, "LOW"), (100, "LOW")]
        for score, expected in cases:
            with self.subTest(score=score):
                self.assertEqual(_risk_level(score), expected)

    def test_safe_like_score_is_not_critical_risk(self):
        scored = score_scan([])
        self.assertEqual(scored["score"], 92)
        self.assertEqual(scored["risk_level"], "LOW")
        self.assertEqual(scored["risk_level_label"], "LOW")
        self.assertIn("score_semantics", scored)

    def test_malicious_like_score_is_not_low_risk(self):
        scored = score_scan([], ml_analysis={
            "available": True, "probability": 0.95,
            "algorithm": "RandomForestClassifier"})
        self.assertLessEqual(scored["score"], 15)
        self.assertEqual(scored["classification"], "MALICIOUS")
        self.assertEqual(scored["risk_level"], "CRITICAL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
