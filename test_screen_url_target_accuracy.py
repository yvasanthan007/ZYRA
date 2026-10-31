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

    def test_browser_bar_capture_precedes_screen_ocr_when_browser_is_foreground(self):
        with patch.object(screen_ocr, "_get_active_browser_url", return_value="https://current-browser.example/login"), \
             patch.object(screen_ocr, "capture_screens") as capture:
            self.assertEqual(screen_ocr.get_active_url(), "https://current-browser.example/login")
        capture.assert_not_called()

    def test_ocr_failure_falls_back_to_browser_url_then_clipboard(self):
        with patch.object(screen_ocr, "_get_active_browser_url", return_value=None), \
             patch.object(screen_ocr, "capture_screens", return_value=[]), \
             patch.object(screen_ocr, "_clipboard_exact_url", return_value=None) as clipboard, \
             patch.object(screen_ocr, "get_url_from_clipboard", return_value=None):
            self.assertIsNone(screen_ocr.get_active_url())
        clipboard.assert_called_once()

    def test_easyocr_receives_numpy_pixels_for_pil_capture(self):
        from PIL import Image
        import numpy as np
        image = Image.new("RGB", (64, 32), color="white")
        reader = type("Reader", (), {"readtext": lambda self, pixels, **kwargs: [
            "https://screen-phish.example/login"
        ]})()
        with patch.object(screen_ocr, "_get_ocr_reader", return_value=reader):
            text = screen_ocr.extract_text_from_image(image)
        self.assertIn("https://screen-phish.example/login", text)
        self.assertIsInstance(np.asarray(image), np.ndarray)

    def test_pil_screen_capture_url_flows_through_to_analysis_capture(self):
        from PIL import Image
        image = Image.new("RGB", (640, 240), color="white")
        with patch.object(screen_ocr, "capture_screens", return_value=[image]), \
             patch.object(screen_ocr, "extract_text_from_image", return_value="https://screen-phish.example/login"), \
             patch.object(screen_ocr, "_get_active_browser_url", return_value=None), \
             patch.object(screen_ocr, "_clipboard_exact_url", return_value=None):
            self.assertEqual(screen_ocr.get_active_url(), "https://screen-phish.example/login")

if __name__ == "__main__":
    unittest.main()





class EasyOcrImageInputTests(unittest.TestCase):
    def test_ocr_passes_numpy_pixels_to_easyocr_for_pil_image(self):
        from PIL import Image
        import numpy as np
        image = Image.new("RGB", (100, 40), "white")
        class Reader:
            def readtext(self, pixels, **kwargs):
                self.pixels = pixels
                return ["https://screen-phish.example/login"]
        reader = Reader()
        with patch.object(screen_ocr, "_get_ocr_reader", return_value=reader):
            text = screen_ocr.extract_text_from_image(image)
        self.assertIsInstance(reader.pixels, np.ndarray)
        self.assertIn("screen-phish.example", text)

    def test_repair_realistic_easyocr_split_and_slash_noise(self):
        self.assertEqual(
            screen_ocr.extract_urls_from_text("https:Ilsecure-login example xyzlaccount"),
            ["https://secure-login.example.xyz/account"],
        )
        self.assertEqual(
            screen_ocr.extract_urls_from_text("https://paypa1-login verify-account-now.xyz/login"),
            ["https://paypa1-login.verify-account-now.xyz/login"],
        )
