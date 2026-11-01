"""Regression tests for the VirusTotal-backed link analysis (backend/link_intel.py).

These lock in the two things a phishing verdict must never get wrong:

  * an authoritative VirusTotal detection outranks the local heuristic/ML;
  * an UNAVAILABLE reputation is never treated as "clean" and never downgrades
    a local detection.

They run fully offline: the network client is stubbed, so no API key or internet
connection is required.
"""

import unittest

from backend import link_intel


MALICIOUS = {"available": True, "verdict_hint": "MALICIOUS",
             "engines": {"malicious": 10, "suspicious": 0, "total": 95}}
FEW_MALICIOUS = {"available": True, "verdict_hint": "MALICIOUS",
                 "engines": {"malicious": 1, "suspicious": 0, "total": 95}}
SUSPICIOUS = {"available": True, "verdict_hint": "SUSPICIOUS",
              "engines": {"malicious": 0, "suspicious": 2, "total": 95}}
CLEAN = {"available": True, "verdict_hint": "CLEAN",
         "engines": {"malicious": 0, "suspicious": 0, "total": 95}}
UNAVAILABLE = {"available": False, "verdict_hint": "UNKNOWN", "note": "quota"}


class FusionTests(unittest.TestCase):
    def fuse(self, verdict, level, points, rep, ml=None):
        return link_intel.fuse_verdict(verdict, level, points, rep, ml)

    def test_malicious_engines_force_critical(self):
        out = self.fuse("SUSPICIOUS", "Low", 0, MALICIOUS)
        self.assertEqual(out["verdict"], "PHISHING DETECTED")
        self.assertEqual(out["risk_score"], "Critical")
        self.assertEqual(out["escalated_by"], "virustotal")

    def test_single_engine_is_still_malicious(self):
        out = self.fuse("SUSPICIOUS", "Low", 0, FEW_MALICIOUS)
        self.assertEqual(out["verdict"], "PHISHING DETECTED")

    def test_suspicious_alone_escalates_to_medium(self):
        out = self.fuse("SUSPICIOUS", "Low", 0, SUSPICIOUS)
        self.assertEqual(out["verdict"], "SUSPICIOUS")
        self.assertEqual(out["risk_score"], "Medium")

    def test_suspicious_corroborated_by_ml(self):
        out = self.fuse("SUSPICIOUS", "Low", 0, SUSPICIOUS, ml=0.8)
        self.assertEqual(out["verdict"], "PHISHING DETECTED")
        self.assertEqual(out["risk_score"], "High")
        self.assertEqual(out["escalated_by"], "virustotal+local")

    def test_suspicious_corroborated_by_heuristic(self):
        out = self.fuse("SUSPICIOUS", "Low", 4, SUSPICIOUS)
        self.assertEqual(out["verdict"], "PHISHING DETECTED")

    def test_unavailable_never_downgrades_a_local_detection(self):
        out = self.fuse("PHISHING DETECTED", "Critical", 9, UNAVAILABLE)
        self.assertEqual(out["verdict"], "PHISHING DETECTED")
        # Unverified evidence caps confidence, it does not erase the finding.
        self.assertEqual(out["risk_score"], "High")

    def test_unavailable_is_not_treated_as_clean(self):
        out = self.fuse("SUSPICIOUS", "Low", 0, UNAVAILABLE)
        self.assertEqual(out["verdict"], "SUSPICIOUS")
        self.assertIn("could not be verified", " ".join(out["reasons"]))

    def test_clean_reputation_does_not_clear_a_local_detection(self):
        out = self.fuse("PHISHING DETECTED", "Critical", 9, CLEAN)
        self.assertEqual(out["verdict"], "PHISHING DETECTED")
        self.assertEqual(out["risk_score"], "Critical")

    def test_fusion_handles_missing_evidence(self):
        out = self.fuse("SUSPICIOUS", "Low", 0, None)
        self.assertEqual(out["verdict"], "SUSPICIOUS")


class LookupTests(unittest.TestCase):
    def setUp(self):
        link_intel.clear_cache()
        link_intel._reset_lookup_clock()

    def tearDown(self):
        link_intel.clear_cache()

    def _stub_threat_intel(self, payload):
        from backend import threat_intel
        original = threat_intel.check_url
        threat_intel.check_url = lambda *a, **k: dict(payload)
        self.addCleanup(setattr, threat_intel, "check_url", original)

    def test_result_is_cached(self):
        self._stub_threat_intel({
            "available": True, "provider": "virustotal", "reputation": "Clean",
            "malware": "Not Detected", "phishing": "Not Detected",
            "engines": {"malicious": 0, "suspicious": 0, "harmless": 90,
                        "undetected": 5, "total": 95},
            "note": "ok",
        })
        first = link_intel.lookup("https://example.org")
        second = link_intel.lookup("https://example.org")
        self.assertTrue(first["available"])
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["engines"]["total"], 95)

    def test_scheme_variants_share_one_cache_entry(self):
        self._stub_threat_intel({
            "available": True, "provider": "virustotal", "reputation": "Clean",
            "engines": {"malicious": 0, "suspicious": 0, "total": 10}, "note": "ok",
        })
        link_intel.lookup("https://Example.org/path#frag")
        hit = link_intel.lookup("example.org/path")
        self.assertTrue(hit["cached"])

    def test_unavailable_is_reported_not_raised(self):
        self._stub_threat_intel({"available": False, "note": "rate limited"})
        out = link_intel.lookup("https://unknown.example")
        self.assertFalse(out["available"])
        self.assertEqual(out["verdict_hint"], "UNKNOWN")
        self.assertIn("rate limited", out["note"])

    def test_empty_url_is_safe(self):
        out = link_intel.lookup("")
        self.assertFalse(out["available"])


class LinkSecurityIntegrationTests(unittest.TestCase):
    def test_analyze_url_security_exposes_threat_intel(self):
        from backend.link_security import analyze_url_security
        result = analyze_url_security("https://example.com")
        self.assertIn("threat_intel", result)
        self.assertIn("reputation_verified", result)
        self.assertIsInstance(result["threat_intel"], dict)
        self.assertIn(result["verdict"], ("SAFE", "SUSPICIOUS", "PHISHING DETECTED"))

    def test_report_states_unverified_explicitly(self):
        from backend.link_security import analyze_url_security, format_security_report
        report = format_security_report(analyze_url_security("https://example.com"))
        self.assertIn("Threat Intelligence:", report)


if __name__ == "__main__":
    unittest.main()
