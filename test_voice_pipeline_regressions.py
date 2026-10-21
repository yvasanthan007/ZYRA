"Offline regression coverage for desktop voice capture, failures and concurrency."""
import threading
import unittest
from unittest import mock
import speech_recognition as sr
import importlib.util
import os
import sys
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, "desktop-ui"))
_spec = importlib.util.spec_from_file_location("bridge_voice_tests", os.path.join(_ROOT, "desktop-ui", "bridge_server.py"))
bridge = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bridge
_spec.loader.exec_module(bridge)

class VoicePipelineRegressionTests(unittest.TestCase):
    def setUp(self):
        bridge._voice_capture_active = False
        bridge._voice_status = "Idle"
        if bridge._voice_capture_lock.locked():
            bridge._voice_capture_lock.release()

    def test_silence_returns_actionable_empty_transcript(self):
        with mock.patch.object(bridge, "_capture_voice_audio", return_value=None):
            result = bridge.handle_message({"type": "voice_toggle", "data": True})
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["transcript"], "")
        self.assertIn("No speech", result["data"]["response"])

    def test_unknown_noisy_input_is_recoverable_empty_transcript(self):
        with mock.patch.object(bridge, "_capture_voice_audio", return_value=object()), \
             mock.patch("listen._recognize", side_effect=sr.UnknownValueError()):
            result = bridge.handle_message({"type": "voice_toggle", "data": True})
        self.assertEqual(result["data"]["transcript"], "")
        self.assertIn("didn't catch", result["data"]["response"])
        self.assertFalse(bridge._voice_capture_lock.locked())

    def test_failed_stt_service_has_clear_error_and_releases_lock(self):
        with mock.patch.object(bridge, "_capture_voice_audio", return_value=object()), \
             mock.patch("listen._recognize", side_effect=sr.RequestError("offline")):
            result = bridge.handle_message({"type": "voice_toggle", "data": True})
        self.assertIn("STT unavailable", result["data"]["error"])
        self.assertFalse(bridge._voice_capture_lock.locked())

    def test_capture_exception_surfaces_as_actionable_error(self):
        with mock.patch.object(bridge, "_capture_voice_audio", side_effect=RuntimeError("device busy")):
            result = bridge.handle_message({"type": "voice_toggle", "data": True})
        self.assertIn("device busy", result["data"]["error"])
        self.assertFalse(bridge._voice_capture_lock.locked())

    def test_concurrent_request_is_rejected_without_opening_second_capture(self):
        entered = threading.Event()
        release = threading.Event()

        def capture(_recognizer):
            entered.set()
            release.wait(2)
            return None
        with mock.patch.object(bridge, "_capture_voice_audio", side_effect=capture):
            worker = threading.Thread(target=bridge.handle_message, args=({"type": "voice_toggle", "data": True},))
            worker.start()
            self.assertTrue(entered.wait(1))
            duplicate = bridge.handle_message({"type": "voice_toggle", "data": True})
            release.set()
            worker.join(2)
        self.assertFalse(duplicate["success"])
        self.assertIn("already in progress", duplicate["error"])
        self.assertFalse(worker.is_alive())

    def test_backend_exception_is_returned_instead_of_swallowed(self):
        with mock.patch.object(bridge, "_capture_voice_audio", return_value=object()), \
             mock.patch("listen._recognize", return_value="open chrome"), \
             mock.patch.object(bridge, "process_voice_command", side_effect=RuntimeError("backend timeout")):
            result = bridge.handle_message({"type": "voice_toggle", "data": True})
        self.assertFalse(result["success"])
        self.assertIn("backend timeout", result["data"]["response"])

    def test_voice_status_reports_active_stage(self):
        bridge._voice_status = "Processing"
        self.assertEqual(bridge.handle_message({"type": "voice_status"})["data"]["status"], "Processing")

if __name__ == "__main__":
    unittest.main(verbosity=2)
