"Regression tests for screen-link requests in chat/voice routing."""
import unittest
from unittest.mock import patch
from backend.url_analyzer.intent import is_url_analysis_intent
from backend.zyra_bridge import _link_capture_report
class ScreenLinkIntentTests(unittest.TestCase):
    def test_natural_screen_phrases_are_url_analysis_intents(self):
        for request in (
            "Analyze this link on screen",
            "Check the website on the screen for phishing",
            "Can you check the link on my screen?",
            "Is the current page safe?",
            "Analyze the page I am on",
        ):
            with self.subTest(request=request):
                self.assertTrue(is_url_analysis_intent(request))

    def test_screen_request_uses_captured_active_url_not_incidental_text_url(self):
        target = "https://screen-phish.example/login"
        with patch("screen_ocr.get_active_url", return_value=target) as capture, \
             patch("backend.zyra_bridge.analyze_url_security", return_value={"ok": True}) as analyze, \
             patch("backend.zyra_bridge.format_security_report", return_value="screen URL analyzed"):
            report, analyzed_url = _link_capture_report(
                "Please check the page on screen, not this URL https://example.org"
            )
        self.assertEqual(analyzed_url, target)
        self.assertEqual(report, "screen URL analyzed")
        capture.assert_called_once()
        analyze.assert_called_once_with(target)

    def test_chat_stream_does_not_treat_screen_request_as_typed_url_scan(self):
        from backend.zyra_bridge import process_chat_stream
        for request in (
            "Analyze the website on the screen",
            "Check the link on my screen",
            "Is the current page safe?",
        ):
            with self.subTest(request=request):
                routed = process_chat_stream(request)
                self.assertEqual(routed["kind"], "capture")

if __name__ == "__main__":
    unittest.main()
