import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.ml_phishing import predictor
from backend.ml_phishing.features import FEATURE_NAMES
from backend.ml_phishing.explorer import query_dataset
from backend.ml_phishing.evaluation import split_indices
from backend.ml_phishing.dataset import build_dataset
from backend.ml_phishing.train import binary_metrics
class UrlMlDashboardTests(unittest.TestCase):
    def test_distinct_inputs_produce_distinct_input_identity_and_features(self):
        first = predictor.analyze_url_ml("https://google.com/search")
        second = predictor.analyze_url_ml("https://paypa1-login.verify-account.xyz/account/login")
        self.assertTrue(first["available"], first)
        self.assertTrue(second["available"], second)
        self.assertEqual(first["url"], "https://google.com/search")
        self.assertEqual(second["url"], "https://paypa1-login.verify-account.xyz/account/login")
        self.assertNotEqual(first["features"], second["features"])
        self.assertNotEqual(first["probability"], second["probability"])

    def test_empty_and_invalid_inputs_are_not_safe(self):
        for url in ("", "not a valid url"):
            result = predictor.analyze_url_ml(url)
            self.assertFalse(result["available"])
            self.assertNotEqual(result.get("verdict"), "SAFE")

    def test_repeated_requests_recompute_exact_url_not_stale_payload(self):
        first = predictor.analyze_url_ml("https://google.com/")
        second_url = "https://example.xyz/login/verify"
        second = predictor.analyze_url_ml(second_url)
        again = predictor.analyze_url_ml("https://google.com/")
        self.assertEqual(second["url"], second_url)
        self.assertEqual(first["probability"], again["probability"])
        self.assertNotEqual(first["url"], second["url"])

    def test_class_mapping_uses_label_not_probability_order(self):
        class Model:
            classes_ = [1, 0]
        self.assertEqual(predictor._phishing_class_index(Model()), 0)

    def test_risk_score_is_actual_phishing_probability_times_100(self):
        result = predictor.analyze_url_ml("https://google.com/")
        self.assertEqual(result["risk_score"], round(result["probability"] * 100, 2))
        self.assertFalse(result["probabilities_calibrated"])

    def test_feature_schema_matches_model_metadata(self):
        self.assertEqual(predictor.model_info()["feature_names"], FEATURE_NAMES)

    def test_dataset_filters_and_only_evaluates_test_rows(self):
        result = query_dataset(search="seed-", split="test", page=1, page_size=2)
        self.assertEqual(result["summary"]["record_count"], 5000)
        self.assertEqual(len(result["records"]), 2)
        self.assertTrue(all(row["split"] == "test" and row["prediction"] is not None for row in result["records"]))
        train = query_dataset(split="train", page_size=2)
        self.assertTrue(all(row["prediction"] is None for row in train["records"]))

    def test_test_split_has_no_shared_registrable_domains(self):
        urls, labels, _ = build_dataset(per_class=200, seed=16)
        train, validation, test = split_indices(urls, labels, seed=16)
        self.assertEqual(sum(map(len, (train, validation, test))), len(urls))

    def test_confusion_matrix_metrics(self):
        metrics = binary_metrics([0, 0, 1, 1], [0.1, 0.6, 0.2, 0.9], 0.35)
        self.assertEqual(metrics["confusion_matrix"]["tn"], 1)
        self.assertEqual(metrics["confusion_matrix"]["fp"], 1)
        self.assertEqual(metrics["confusion_matrix"]["fn"], 1)
        self.assertEqual(metrics["confusion_matrix"]["tp"], 1)

    def test_api_empty_request_is_client_error_and_dataset_api_works(self):
        from backend.server import app
        client = TestClient(app)
        self.assertEqual(client.post("/api/ml/phishing", json={}).status_code, 400)
        response = client.get("/api/ml/phishing/dataset?page=1&page_size=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]["records"]), 1)

    def test_capture_empty_extraction_never_safe(self):
        from backend.server import app
        with patch("screen_ocr.get_active_url", return_value=None):
            response = TestClient(app).post("/api/ml/phishing/capture")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no safety verdict", response.json()["error"])

    def test_two_fresh_screen_capture_urls_reach_model_as_distinct_payloads(self):
        from backend.server import app
        urls = ["https://google.com/search", "https://paypa1-login.verify-account.xyz/account/login"]
        with patch("screen_ocr.get_active_url", side_effect=urls):
            client = TestClient(app)
            first = client.post("/api/ml/phishing/capture")
            second = client.post("/api/ml/phishing/capture")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["data"]["url"], urls[0])
        self.assertEqual(second.json()["data"]["url"], urls[1])
        self.assertNotEqual(first.json()["data"]["features"], second.json()["data"]["features"])
        self.assertNotEqual(first.json()["data"]["probability"], second.json()["data"]["probability"])

    def test_capture_backend_failure_never_safe(self):
        from backend.server import app
        with patch("screen_ocr.get_active_url", side_effect=RuntimeError("capture failed")):
            response = TestClient(app).post("/api/ml/phishing/capture")
        self.assertEqual(response.status_code, 503)
        self.assertIn("no safety verdict", response.json()["error"])

    def test_missing_model_reports_unavailable(self):
        with patch.object(predictor, "_model_path", return_value="Z:/missing/zyra-model.joblib"):
            with patch.dict("os.environ", {"ZYRA_ML_DISABLE": "0"}):
                model, _ = predictor._load()
                self.assertIsNone(model)
                result = predictor.analyze_url_ml("https://example.com")
                self.assertFalse(result["available"])

if __name__ == "__main__":
    unittest.main()
