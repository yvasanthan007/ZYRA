"Regression tests for OCR target selection and URL repair."""
import unittest
from unittest.mock import patch
import screen_ocr
class ScreenUrlAccuracyTests(unittest.TestCase):
    def test_spaced_ocr_url_restores_actual_host_and_path(self):
        text = "Address bar https:// secure-login . xyz / verify"
        self.assertEqual(screen_ocr.extract_urls_from_text(text), ["https://secure-login.xyz/verify"])

    def test_separate_urls_are_not_merged_into_fabricated_url(self):
        text = "https://evil.example.com/login Google search https://google.com"
        self.assertEqual(screen_ocr.extract_urls_from_text(text), [
            "https://evil.example.com/login", "https://google.com",
        ])

    def test_screen_capture_is_used_before_clipboard_fallback(self):
        with patch.object(screen_ocr, "_capture_url_isolated", return_value="https://evil.example.com/login"), \
             patch.object(screen_ocr, "_clipboard_exact_url") as clipboard:
            self.assertEqual(screen_ocr.get_active_url(), "https://evil.example.com/login")
        clipboard.assert_not_called()

if __name__ == "__main__":
    unittest.main()

