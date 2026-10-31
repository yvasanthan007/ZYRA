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
        with patch.object(screen_ocr, "capture_screens", return_value=[object()]), \
             patch.object(screen_ocr, "extract_urls_from_image", return_value=["https://evil.example.com/login"]), \
             patch.object(screen_ocr, "_clipboard_exact_url") as clipboard:
            self.assertEqual(screen_ocr.get_active_url(), "https://evil.example.com/login")
        clipboard.assert_not_called()

    def test_screen_ocr_uses_address_bar_then_full_image(self):
        class FakeImage:
            size = (1600, 900)

            def crop(self, box):
                self.crop_box = box
                return self
        image = FakeImage()
        with patch.object(screen_ocr, "extract_text_from_image", side_effect=[
            "https://screen-phish.xyz/login", "https://unrelated-page-link.example.com/"
        ]) as ocr:
            self.assertEqual(screen_ocr.extract_urls_from_image(image), [
                "https://screen-phish.xyz/login",
            ])
        self.assertEqual(ocr.call_count, 1)
        self.assertEqual(image.crop_box, (0, 0, 1600, 216))

    def test_ocr_failure_falls_back_to_browser_url_then_clipboard(self):
        with patch.object(screen_ocr, "capture_screens", return_value=[]), \
             patch.object(screen_ocr, "_get_active_browser_url", return_value="https://active.example.com/login"), \
             patch.object(screen_ocr, "_clipboard_exact_url") as clipboard:
            self.assertEqual(screen_ocr.get_active_url(), "https://active.example.com/login")
        clipboard.assert_not_called()

if __name__ == "__main__":
    unittest.main()

