"Regression tests for broad URL recognition and XGBoost model selection."""
import unittest
from backend.link_security import extract_url
from backend.ml_phishing import predictor
from backend.ml_phishing.train import train_models
from screen_ocr import extract_urls_from_text
class BroadUrlRecognitionTests(unittest.TestCase):
    def test_new_generic_tld_in_message(self):
        self.assertEqual(
            extract_url("Please check https://example.tools/account/login now"),
            "https://example.tools/account/login",
        )

    def test_country_code_and_long_tld_in_message(self):
        self.assertEqual(extract_url("check portal.example.photography/reset"),
                         "portal.example.photography/reset")
        self.assertEqual(extract_url("open https://example.corporate"),
                         "https://example.corporate")

    def test_screen_text_accepts_unlisted_tld_but_ignores_code_dot_names(self):
        self.assertEqual(extract_urls_from_text("Current page: https://example.tools/login"),
                         ["https://example.tools/login"])
        self.assertEqual(extract_urls_from_text("fastapi.testclient torch.dataloader"), [])

class XGBoostSelectionTests(unittest.TestCase):
    def test_inference_uses_xgboost_model(self):
        info = predictor.model_info()
        if not info.get("available"):
            self.skipTest(info.get("note", "trained model unavailable"))
        self.assertEqual(info.get("algorithm"), "XGBClassifier")
        result = predictor.analyze_url_ml(
            "https://paypa1-login.verify-account.xyz/account/login")
        self.assertTrue(result.get("available"), result)
        self.assertEqual(result.get("algorithm"), "XGBClassifier")

    def test_training_prefers_xgboost_when_installed(self):
        try:
            import xgboost  # noqa: F401
        except Exception:
            self.skipTest("XGBoost unavailable")
        from backend.ml_phishing.dataset import build_dataset
        urls, labels, _stats = build_dataset(per_class=100, seed=11)
        name, _model, results, _holdout = train_models(
            urls, labels, n_estimators=10, seed=11, verbose=False)
        self.assertIn("XGBClassifier", results)
        self.assertEqual(name, "XGBClassifier")

if __name__ == "__main__":
    unittest.main(verbosity=2)
