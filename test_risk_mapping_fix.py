"""
Regression tests: safety-score → risk-level mapping (backend/url_analyzer).

A safety score of 0-100 is HIGHER = SAFER (the inverse of the ML phishing
probability where higher = more dangerous). Therefore:
    0-24   -> CRITICAL risk
    25-49  -> HIGH
    50-74  -> MEDIUM
    75-100 -> LOW
"""

import unittest

from backend.url_analyzer.risk_scorer import _risk_level, score_scan


class SafetyRiskMappingTests(unittest.TestCase):
    """Score→risk mapping must follow safety-score semantics, not ML ones."""

    def test_risk_level_boundaries(self):
        cases = [
            (0, "CRITICAL"), (24, "CRITICAL"),
            (25, "HIGH"), (49, "HIGH"),
            (50, "MEDIUM"), (74, "MEDIUM"),
            (75, "LOW"), (100, "LOW"),
        ]
        for score, expected in cases:
            self.assertEqual(_risk_level(score), expected, f"score={score}")

    def test_malicious_like_score_is_not_low_risk(self):
        # A near-dead safety score must never render as LOW risk.
        self.assertEqual(_risk_level(10), "CRITICAL")
        self.assertEqual(_risk_level(18), "CRITICAL")
        self.assertNotEqual(_risk_level(18), "LOW")

    def test_safe_like_score_is_not_critical_risk(self):
        # A high safety score must never render as CRITICAL risk.
        self.assertEqual(_risk_level(92), "LOW")
        self.assertEqual(_risk_level(95), "LOW")
        self.assertNotEqual(_risk_level(92), "CRITICAL")

    def test_non_int_and_out_of_range_scores(self):
        self.assertEqual(_risk_level(None), "UNKNOWN")
        self.assertEqual(_risk_level("not-a-number"), "UNKNOWN")
        self.assertEqual(_risk_level(150), "LOW")    # clamped to 100
        self.assertEqual(_risk_level(-5), "CRITICAL")  # clamped to 0

    def test_score_scan_output_carries_semantics(self):
        res = score_scan(
            [],
            domain_info={"resolved": True, "whois_available": True},
            ssl_info={"checked": True, "valid": True},
            reputation={"available": True, "reputation": "clean"},
        )
        self.assertIn("score_semantics", res)
        self.assertIn("higher = safer", res["score_semantics"])
        # Safe scan: high safety score must map to LOW risk, not CRITICAL.
        self.assertGreaterEqual(res["score"], 75)
        self.assertEqual(res["risk_level"], "LOW")
        self.assertEqual(res["risk_level_label"], "LOW")


if __name__ == "__main__":
    unittest.main()
