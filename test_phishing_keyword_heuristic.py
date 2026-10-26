import unittest
from backend.url_analyzer.threat_detector import (
    analyze_keyword_signals,
    detect_threats,
)

class KeywordHeuristicTests(unittest.TestCase):
    def _findings(self, url):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        parts = {"hostname": parsed.hostname, "path": parsed.path,
                 "query": parsed.query, "scheme": parsed.scheme,
                 "port": parsed.port}
        return detect_threats(url, parts, domain_info={"registered_domain": parsed.hostname})

    def test_correlated_encoded_case_insensitive_keywords_are_found_by_component(self):
        matches, points = analyze_keyword_signals(
            "evil.test", "/%61ccount-verification", "next=CLAIM-PRIZE")
        self.assertGreater(points, 0)
        self.assertEqual({m["keyword"] for m in matches},
                         {"account-verification", "claim-prize"})
        self.assertIn("path", matches[0]["locations"])
        self.assertIn("query", matches[1]["locations"])

    def test_all_requested_phrases_have_category_coverage(self):
        expected = {
            "credential_theft": {"login", "signin", "verify", "password", "reset-password", "account-verification"},
            "urgency_threats": {"urgent", "immediate-action", "suspended", "blocked", "account-locked", "unusual-activity"},
            "financial_fraud": {"bank", "banking", "payment", "refund", "invoice", "transaction", "wallet", "crypto"},
            "malicious_actions": {"malicious", "phishing", "steal", "validate", "unlock", "recover-account"},
            "deception_delivery": {"secure-update", "confirm-identity", "claim-prize", "free-gift", "download-now", "click-here"},
            "sensitive_information": {"OTP", "PIN", "CVV", "card-details", "social-security", "recovery-code"},
        }
        from backend.url_analyzer.threat_detector import KEYWORD_GROUPS
        for category, terms in expected.items():
            self.assertTrue(terms.issubset(set(KEYWORD_GROUPS[category])))

    def test_common_standalone_keywords_are_advisory(self):
        for url in ("https://login.example.com/", "https://bank.example.com/update"):
            findings = self._findings(url)
            keyword = next(f for f in findings if f["id"] == "phishing_keyword_signals")
            self.assertEqual(keyword["score_impact"], 0)
            self.assertEqual(keyword["severity"], "INFO")

    def test_combined_lure_generates_weighted_finding(self):
        findings = self._findings(
            "https://service.example.net/verify-account/urgent-action?payment=OTP")
        keyword = next(f for f in findings if f["id"] == "phishing_keyword_signals")
        self.assertGreater(keyword["score_impact"], 0)
        self.assertIn("Matched keyword(s)", keyword["detail"])

    def test_benign_vendor_help_link_only_gets_advisory_keyword_finding(self):
        findings = self._findings("https://support.microsoft.com/account/login-help")
        keyword = next(f for f in findings if f["id"] == "phishing_keyword_signals")
        self.assertEqual(keyword["score_impact"], 0)
        self.assertIsNone(next((f for f in findings if f["id"] == "typosquatting"), None))

    def test_keyword_finding_does_not_duplicate_xgboost_features(self):
        from backend.ml_phishing.features import FEATURE_NAMES
        self.assertNotIn("phishing_keyword_signals", FEATURE_NAMES)

    def test_legacy_link_security_reports_correlated_keywords(self):
        from backend.link_security import analyze_url_security
        result = analyze_url_security("https://service.example.net/verify-account/urgent-action?payment=OTP")
        self.assertNotEqual(result["verdict"], "SAFE")
        self.assertTrue(any("Matched phishing-related keywords" in item
                            for item in result["observations"]))

if __name__ == "__main__":
    unittest.main()

    def test_classifier_cannot_lower_validated_high_risk_finding(self):
        from backend.url_analyzer.risk_scorer import score_scan
        finding = {"id": "phishing_keyword_signals", "severity": "HIGH",
                   "score_impact": 30, "title": "Correlated lure"}
        result = score_scan([finding], domain_info={"resolved": True},
                            reputation={"available": True, "reputation": "clean"},
                            ml_analysis={"available": True, "probability": 0.01})
        self.assertEqual(result["classification"], "SUSPICIOUS")

    def test_classifier_high_probability_remains_malicious_with_heuristic(self):
        from backend.url_analyzer.risk_scorer import score_scan
        finding = {"id": "phishing_keyword_signals", "severity": "HIGH",
                   "score_impact": 30, "title": "Correlated lure"}
        result = score_scan([finding], ml_analysis={"available": True, "probability": 0.95})
        self.assertEqual(result["classification"], "MALICIOUS")
