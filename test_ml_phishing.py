"""
test_ml_phishing.py — Tests for ZYRA's ML phishing classifier layer.

Run:  python -m pytest test_ml_phishing.py -v
(or)  python test_ml_phishing.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.ml_phishing import predictor
from backend.ml_phishing.features import (
    FEATURE_NAMES,
    extract_features,
    feature_vector,
)
from backend.ml_phishing.predictor import analyze_url_ml
from backend.url_analyzer.risk_scorer import score_scan

PHISH_SAMPLE = "http://paypa1-secure-login.verify-account-now.xyz/login.php?token=a1b2c3d4e5f60718"
LEGIT_SAMPLE = "https://www.amazon.com/dp/B08N5WRWNW?ref_=header_logo"


class FeatureExtractionTests(unittest.TestCase):
    def test_feature_vector_shape_and_types(self):
        vec = feature_vector(PHISH_SAMPLE)
        self.assertEqual(len(vec), len(FEATURE_NAMES))
        for value in vec:
            self.assertIsInstance(value, float)

    def test_ip_host_and_credential_keywords_flagged(self):
        feats = extract_features("http://192.168.13.37/paypal/login.php")
        self.assertEqual(feats["has_ip_host"], 1)
        self.assertGreaterEqual(feats["credential_keywords"], 1)
        self.assertEqual(feats["is_https"], 0)

    def test_https_legit_flags(self):
        feats = extract_features(LEGIT_SAMPLE)
        self.assertEqual(feats["is_https"], 1)
        self.assertEqual(feats["has_ip_host"], 0)
        self.assertEqual(feats["suspicious_tld"], 0)

    def test_shortener_flagged(self):
        feats = extract_features("https://bit.ly/3nKx2pQ")
        self.assertEqual(feats["is_shortener"], 1)

    def test_buried_subdomains_flagged(self):
        feats = extract_features(
            "http://paypal.com.login.secure12.verify.xyz/account/verify")
        self.assertGreaterEqual(feats["num_subdomains"], 3)
        self.assertEqual(feats["suspicious_tld"], 1)

    def test_empty_and_garbage_urls_stay_stable(self):
        for bad in ("", "   ", "not a url", "http://", "://bad"):
            feats = extract_features(bad)
            self.assertEqual(len(feats), len(FEATURE_NAMES))
            for name in FEATURE_NAMES:
                self.assertIsInstance(feats[name], (int, float))


class ScoreScanIntegrationTests(unittest.TestCase):
    def test_ml_high_probability_forces_malicious(self):
        scored = score_scan([], ml_analysis={
            "available": True, "probability": 0.95,
            "algorithm": "RandomForestClassifier"})
        self.assertEqual(scored["classification"], "MALICIOUS")
        self.assertLessEqual(scored["score"], 15)

    def test_ml_medium_raises_clean_url_to_suspicious(self):
        scored = score_scan([], ml_analysis={
            "available": True, "probability": 0.80,
            "algorithm": "RandomForestClassifier"})
        self.assertEqual(scored["classification"], "SUSPICIOUS")

    def test_ml_safe_changes_nothing(self):
        base = score_scan([])
        ml = score_scan([], ml_analysis={
            "available": True, "probability": 0.05, "algorithm": "X"})
        self.assertEqual(base["classification"], ml["classification"])
        self.assertEqual(base["score"], ml["score"])

    def test_ml_unavailable_or_lowconfidence_no_effect(self):
        base = score_scan([])
        for ml in (None, {"available": False, "probability": 0.99},
                   {"available": True, "probability": 0.30}):
            scored = score_scan([], ml_analysis=ml)
            self.assertEqual(base["classification"], scored["classification"])

    def test_ml_reasoning_present(self):
        scored = score_scan([], ml_analysis={
            "available": True, "probability": 0.91, "algorithm": "RandomForest"})
        self.assertTrue(any("ML phishing classifier" in line
                            for line in scored["reasoning"]))

@unittest.skipUnless(
    predictor.model_info().get("available"),
    "trained model not present (run: python -m backend.ml_phishing.train)")
class PredictorTests(unittest.TestCase):
    def test_model_info_available(self):
        info = predictor.model_info()
        self.assertTrue(info["available"])
        self.assertIn("algorithm", info)
        self.assertIn("metrics", info)

    def test_obvious_phish_scores_high(self):
        result = analyze_url_ml(PHISH_SAMPLE)
        self.assertTrue(result["available"])
        self.assertGreaterEqual(result["probability"], 0.60)
        self.assertIn(result["verdict"],
                      ("PHISHING", "LIKELY_PHISHING", "SUSPICIOUS"))
        self.assertIsInstance(result["top_signals"], list)

    def test_legit_site_scores_low(self):
        result = analyze_url_ml(LEGIT_SAMPLE)
        self.assertTrue(result["available"])
        self.assertLess(result["probability"], 0.50)

    def test_brand_subdomain_lure_flagged(self):
        result = analyze_url_ml(
            "https://paypal.com.verify-suspension-4821.tk/account/verify?token=ff0099aabb001122")
        self.assertTrue(result["available"])
        self.assertGreaterEqual(result["probability"], 0.60)

    def test_garbage_never_raises_and_shapes_are_stable(self):
        for bad in (None, "", "   ", "not a url"):
            result = analyze_url_ml(bad)
            self.assertIsInstance(result, dict)
            self.assertIn("available", result)

    def test_verdict_tiers_consistent_with_risk_scorer(self):
        # 0.90+ must map to MALICIOUS in score_scan and PHISHING in predictor
        result = analyze_url_ml(PHISH_SAMPLE)
        if result["available"] and result["probability"] >= 0.90:
            scored = score_scan([], ml_analysis=result)
            self.assertEqual(scored["classification"], "MALICIOUS")


class TrainingSmokeTests(unittest.TestCase):
    def test_train_small_model_end_to_end(self):
        from backend.ml_phishing import train
        from backend.ml_phishing.dataset import build_dataset

        urls, labels, stats = build_dataset(per_class=150, seed=7)
        self.assertGreaterEqual(len(urls), 280)
        self.assertEqual(stats["phishing"], stats["legitimate"])

        best_name, best_model, results, holdout = train.train_models(
            urls, labels, n_estimators=25, seed=7, verbose=False)
        self.assertEqual(set(results),
                         {"RandomForestClassifier", "LogisticRegression"})
        self.assertGreater(results[best_name]["f1"], 0.85)
        X_test, y_test = holdout
        self.assertEqual(len(X_test), len(y_test))


class MlApiTests(unittest.TestCase):
    def test_ml_phishing_endpoint(self):
        try:
            from fastapi.testclient import TestClient
            from backend.server import app
        except Exception:
            self.skipTest("server dependencies unavailable")
        client = TestClient(app)
        resp = client.post("/api/ml/phishing", json={"url": PHISH_SAMPLE})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("success"))
        self.assertTrue(body["data"]["available"])

        missing = client.post("/api/ml/phishing", json={})
        self.assertEqual(missing.status_code, 400)

    def test_ml_model_metadata_endpoint(self):
        try:
            from fastapi.testclient import TestClient
            from backend.server import app
        except Exception:
            self.skipTest("server dependencies unavailable")
        client = TestClient(app)
        resp = client.get("/api/ml/phishing/model")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("success"))

if __name__ == "__main__":
    unittest.main(verbosity=2)

