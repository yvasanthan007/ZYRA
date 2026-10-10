"""
Regression tests: ML reliability guard in risk scoring.

Rules:
  - ML phishing PROBABILITY (higher = more danger) must never be confused
    with the SAFETY SCORE (higher = safer).
  - A URL shortener masks the destination: with no reputation data AND no
    ML suspicion the classification must be UNKNOWN, never LIKELY_SAFE.
  - High ML probability still forces MALICIOUS (the guard must not weaken
    a strong signal).
"""

import unittest

from backend.url_analyzer.risk_scorer import score_scan
from backend.ml_phishing.features import extract_features


def _shortener_finding():
    return {
        "id": "url_shortener", "severity": "MEDIUM", "category": "obfuscation",
        "title": "URL shortener masks the destination",
        "detail": "Shortened links hide the real destination until after the "
                  "redirect, which is commonly abused in phishing messages.",
        "score_impact": 10, "positive": False,
    }


def _base_context():
    return dict(
        domain_info={"resolved": True, "whois_available": True},
        ssl_info={"checked": True, "valid": True},
    )


class MlReliabilityGuardTests(unittest.TestCase):
    def test_shortener_low_ml_no_reputation_is_unknown(self):
        res = score_scan(
            [_shortener_finding()], reputation={"available": False},
            ml_analysis={"available": True, "probability": 0.10},
            **_base_context(),
        )
        self.assertEqual(res["classification"], "UNKNOWN")

    def test_shortener_no_ml_no_reputation_is_unknown(self):
        res = score_scan(
            [_shortener_finding()], reputation={"available": False},
            **_base_context(),
        )
        self.assertEqual(res["classification"], "UNKNOWN")

    def test_shortener_with_reputation_stays_classifiable(self):
        res = score_scan(
            [_shortener_finding()],
            reputation={"available": True, "reputation": "clean"},
            **_base_context(),
        )
        self.assertNotEqual(res["classification"], "UNKNOWN")

    def test_shortener_high_ml_still_malicious(self):
        res = score_scan(
            [_shortener_finding()], reputation={"available": False},
            ml_analysis={"available": True, "probability": 0.95,
                         "algorithm": "RandomForest"},
            **_base_context(),
        )
        self.assertEqual(res["classification"], "MALICIOUS")
        self.assertLessEqual(res["score"], 15)

    def test_ml_probability_and_safety_score_not_confused(self):
        res = score_scan(
            [], reputation={"available": True, "reputation": "clean"},
            ml_analysis={"available": True, "probability": 0.10},
            **_base_context(),
        )
        self.assertIn("score_semantics", res)
        self.assertIn("higher = safer", res["score_semantics"])
        # A clean scan has a HIGH safety score → LOW risk — even though the
        # ML probability semantics run the other way.
        self.assertGreaterEqual(res["score"], 75)
        self.assertEqual(res["risk_level"], "LOW")

    def test_benign_login_query_and_port_shapes(self):
        feats = extract_features("https://example.com:8443/account?next=login")
        self.assertEqual(feats["is_shortener"], 0)
        self.assertEqual(feats["suspicious_tld"], 0)
        self.assertEqual(feats["has_ip_host"], 0)
        self.assertEqual(feats["is_https"], 1)

        res = score_scan(
            [], reputation={"available": True, "reputation": "clean"},
            ml_analysis={"available": True, "probability": 0.12},
            **_base_context(),
        )
        self.assertNotEqual(res["classification"], "MALICIOUS")
        self.assertIn(res["classification"], ("LIKELY_SAFE", "SUSPICIOUS"))

    def test_suspicious_tld_ip_and_malformed_inputs(self):
        tld = {
            "id": "suspicious_tld", "severity": "MEDIUM", "category": "domain",
            "title": "High-risk top-level domain '.xyz'",
            "detail": "Heavily abused in phishing campaigns.",
            "score_impact": 10, "positive": False,
        }
        res = score_scan(
            [tld], reputation={"available": False},
            ml_analysis={"available": True, "probability": 0.20},
            **_base_context(),
        )
        self.assertIn(res["classification"], ("LIKELY_SAFE", "SUSPICIOUS"))

        ip = {
            "id": "ip_host", "severity": "CRITICAL", "category": "domain",
            "title": "Raw IP address host",
            "detail": "Login pages do not live on bare IPs.",
            "score_impact": 40, "positive": False,
        }
        res2 = score_scan(
            [ip], reputation={"available": True, "reputation": "clean"},
            **_base_context(),
        )
        self.assertEqual(res2["classification"], "MALICIOUS")
        self.assertLess(res2["score"], 70)


if __name__ == "__main__":
    unittest.main()
