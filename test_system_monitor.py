"""
test_system_monitor.py — Comprehensive Test Suite for ZYRA System Monitor
Tests metric collection, intent routing, formatted outputs, voice integration,
bridge processing, and backend API endpoints.
"""

import os
import sys
import time
import unittest
from typing import Dict, Any
from unittest import mock

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_monitor import (
    get_system_metrics,
    format_system_monitor_text,
    get_voice_summary,
    is_system_monitor_intent,
    classify_system_query,
    answer_system_query,
    top_processes,
    start_system_monitor,
    make_progress_bar,
    format_bytes,
    format_speed,
    analyze_system_health,
    SystemMonitor,
)
from backend.zyra_bridge import (
    process_chat,
    process_chat_stream,
    process_command,
    process_voice_command,
    process_message,
    COMMAND_MAP,
)
from backend import server as server_module
from backend.server import app
from fastapi.testclient import TestClient

class TestSystemMonitor(unittest.TestCase):
    """Test suite for System Monitor metrics, formatting, and intent detection."""

    def test_metrics_structure(self):
        """Test that get_system_metrics returns all required fields."""
        metrics = get_system_metrics()
        self.assertTrue(metrics.get("success"))

        # CPU
        self.assertIn("cpu", metrics)
        self.assertIn("percent", metrics["cpu"])
        self.assertIsInstance(metrics["cpu"]["percent"], (int, float))
        self.assertGreaterEqual(metrics["cpu"]["percent"], 0.0)
        self.assertLessEqual(metrics["cpu"]["percent"], 100.0)
        self.assertIn("bar", metrics["cpu"])

        # Memory
        self.assertIn("memory", metrics)
        self.assertIn("percent", metrics["memory"])
        self.assertIn("used_str", metrics["memory"])
        self.assertIn("available_str", metrics["memory"])
        self.assertIn("total_str", metrics["memory"])
        self.assertIn("bar", metrics["memory"])

        # Disk
        self.assertIn("disk", metrics)
        self.assertIn("percent", metrics["disk"])
        self.assertIn("used_str", metrics["disk"])
        self.assertIn("free_str", metrics["disk"])
        self.assertIn("total_str", metrics["disk"])
        self.assertIn("bar", metrics["disk"])

        # Network
        self.assertIn("network", metrics)
        self.assertIn("download_speed_str", metrics["network"])
        self.assertIn("upload_speed_str", metrics["network"])
        self.assertIn("total_sent_str", metrics["network"])
        self.assertIn("total_recv_str", metrics["network"])

        # Battery
        self.assertIn("battery", metrics)
        self.assertIn("percent_str", metrics["battery"])
        self.assertIn("charging_str", metrics["battery"])

        # Uptime
        self.assertIn("uptime", metrics)
        self.assertIn("formatted", metrics["uptime"])

        # System
        self.assertIn("system", metrics)
        self.assertIn("os", metrics["system"])
        self.assertIn("formatted", metrics["system"])

        # Health Analysis
        self.assertIn("analysis", metrics)
        self.assertIn("status", metrics["analysis"])
        self.assertIn("description", metrics["analysis"])
        self.assertIn("level", metrics["analysis"])

    def test_health_analysis_logic(self):
        """Test health status analysis thresholds and descriptions."""
        # Normal
        norm = analyze_system_health(35.0, 55.0, 50.0)
        self.assertEqual(norm["status"], "NORMAL")
        self.assertEqual(norm["level"], "normal")

        # Low activity
        low = analyze_system_health(5.0, 30.0, 40.0)
        self.assertEqual(low["status"], "LOW ACTIVITY")
        self.assertEqual(low["level"], "low")

        # High resource usage
        high = analyze_system_health(82.0, 70.0, 50.0)
        self.assertEqual(high["status"], "HIGH RESOURCE USAGE")
        self.assertEqual(high["level"], "elevated")

        # Warning (CPU)
        warn_cpu = analyze_system_health(95.0, 60.0, 50.0)
        self.assertEqual(warn_cpu["status"], "WARNING")
        self.assertEqual(warn_cpu["level"], "warning")

        # Warning (RAM)
        warn_ram = analyze_system_health(40.0, 94.0, 50.0)
        self.assertEqual(warn_ram["status"], "WARNING")
        self.assertEqual(warn_ram["level"], "warning")

        # Warning (Disk)
        warn_disk = analyze_system_health(40.0, 50.0, 98.0)
        self.assertEqual(warn_disk["status"], "WARNING")
        self.assertEqual(warn_disk["level"], "warning")

    def test_intent_detection(self):
        """Test trigger phrases for System Monitor."""
        triggers = [
            "Monitor my system",
            "monitor my system",
            "MONITOR MY SYSTEM",
            "Start system monitor",
            "open system monitor",
            "show system monitor",
            "system monitor",
            "monitor the system",
            "monitor system",
            "check system monitor",
            "run system monitor",
            "system monitoring",
        ]
        for phrase in triggers:
            self.assertTrue(is_system_monitor_intent(phrase), f"Failed for: '{phrase}'")

        non_triggers = [
            "open chrome",
            "what is the time",
            "search google for dogs",
            "play music",
            "tell me a joke",
        ]
        for phrase in non_triggers:
            self.assertFalse(is_system_monitor_intent(phrase), f"False positive for: '{phrase}'")

    def test_formatted_text_output(self):
        """Test that formatted text contains all required dashboard sections."""
        text = format_system_monitor_text()
        self.assertIn("SYSTEM MONITOR", text)
        self.assertIn("CPU", text)
        self.assertIn("RAM", text)
        self.assertIn("DISK", text)
        self.assertIn("NETWORK", text)
        self.assertIn("Download", text)
        self.assertIn("Upload", text)
        self.assertIn("BATTERY", text)
        self.assertIn("Charging", text)
        self.assertIn("UPTIME", text)
        self.assertIn("SYSTEM", text)
        self.assertIn("System Status:", text)

    def test_progress_bar_generation(self):
        """Test ASCII progress bar output."""
        bar_0 = make_progress_bar(0)
        self.assertEqual(bar_0, "░░░░░░░░░░")

        bar_100 = make_progress_bar(100)
        self.assertEqual(bar_100, "██████████")

        bar_50 = make_progress_bar(50)
        self.assertEqual(len(bar_50), 10)
        self.assertEqual(bar_50.count("█"), 5)
        self.assertEqual(bar_50.count("░"), 5)

    def test_voice_summary(self):
        """Test voice summary text."""
        summary = get_voice_summary()
        self.assertIn("System Monitor", summary)
        self.assertIn("CPU", summary)
        self.assertIn("memory", summary)
        self.assertIn("disk", summary)

    def test_bridge_command_map(self):
        """Test that monitor_system is registered in COMMAND_MAP."""
        self.assertIn("monitor_system", COMMAND_MAP)
        self.assertIn("system_monitor", COMMAND_MAP)
        result = COMMAND_MAP["monitor_system"]()
        self.assertIn("SYSTEM MONITOR", result)

    def test_bridge_process_command(self):
        """Test programmatic command execution via bridge."""
        res = process_command("monitor_system")
        self.assertTrue(res.get("success"))
        self.assertIn("Executed monitor_system", res.get("data", ""))

    def test_bridge_process_voice_command(self):
        """Test voice command processing for 'Monitor my system'."""
        res = process_voice_command("Monitor my system")
        self.assertEqual(res.get("action"), "system_monitor")
        self.assertIn("System Monitor", res.get("response", ""))
        self.assertIn("metrics", res)

    def test_bridge_process_chat(self):
        """Test chat input processing for System Monitor."""
        res = process_chat("Monitor my system")
        self.assertIn("SYSTEM MONITOR", res)

    def test_bridge_process_message(self):
        """Test WebSocket message handler for system_metrics."""
        res = process_message("system_metrics", None)
        self.assertTrue(res.get("success"))
        self.assertIn("data", res)
        self.assertIn("cpu", res["data"])

    def test_api_system_metrics(self):
        """Test FastAPI /api/system/metrics endpoint."""
        client = TestClient(app)
        response = client.get("/api/system/metrics")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIn("data", data)
        self.assertIn("cpu", data["data"])
        self.assertIn("memory", data["data"])

    def test_api_system_monitor_trigger(self):
        """Test FastAPI /api/system/monitor POST endpoint."""
        client = TestClient(app)
        response = client.post("/api/system/monitor")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIn("formatted", data)
        self.assertIn("SYSTEM MONITOR", data["formatted"])


    # ──────────────────────────────────────────────
    # Natural-language question routing (regression: metric questions used to
    # fall through to the language model, which has no access to this machine)
    # ──────────────────────────────────────────────

    def test_question_topics_are_classified(self):
        """Realistic questions map onto the metric topic they ask about."""
        cases = {
            "what is my cpu usage": "cpu",
            "whats my cpu usage right now": "cpu",
            "how much ram is being used": "ram",
            "memory usage": "ram",
            "is my disk full": "disk",
            "how much disk space is left": "disk",
            "check my battery": "battery",
            "is my battery charging": "battery",
            "how long has my pc been on": "uptime",
            "what is my uptime": "uptime",
            "is my pc overheating": "temperature",
            "what processes are using the most memory": "processes",
            "which app is eating my cpu": "processes",
            "what is my ip address": "network",
            "how fast is my internet": "network",
            "tell me my system info": "system",
            "monitor my system": "overall",
            "system status": "overall",
            "why is my computer slow": "overall",
            "system performance": "overall",
        }
        for question, expected in cases.items():
            self.assertEqual(
                classify_system_query(question), expected,
                f"wrong topic for {question!r}")
            self.assertTrue(is_system_monitor_intent(question), question)

    def test_unrelated_messages_are_not_hijacked(self):
        """Normal chat must never be routed to the system monitor."""
        for message in (
            "open chrome",
            "what is the time",
            "search google for dogs",
            "play music",
            "tell me a joke",
            "what is 2 plus 3",
            "name one colour",
            "thanks",
            "why is the sky blue",
            "python memory usage",
            "what is node memory usage",
            "how do I free up disk space",
            "write a function to get cpu usage",
            "is my code slow",
            "open notepad",
        ):
            self.assertIsNone(classify_system_query(message), message)
            self.assertFalse(is_system_monitor_intent(message), message)

    def test_answers_use_real_metrics(self):
        """Each topic answers with live values, never model guesses."""
        metrics = get_system_metrics()
        cpu_answer = answer_system_query("what is my cpu usage", metrics)
        self.assertIn(f"{int(round(metrics['cpu']['percent']))}%", cpu_answer)

        ram_answer = answer_system_query("how much ram is being used", metrics)
        self.assertIn(metrics["memory"]["total_str"], ram_answer)

        disk_answer = answer_system_query("is my disk full", metrics)
        self.assertIn(metrics["disk"]["total_str"], disk_answer)

        uptime_answer = answer_system_query("how long has my pc been on", metrics)
        self.assertIn(metrics["uptime"]["formatted"], uptime_answer)

        system_answer = answer_system_query("tell me my system info", metrics)
        self.assertIn(metrics["system"]["hostname"], system_answer)

        battery_answer = answer_system_query("check my battery", metrics)
        self.assertIn("battery", battery_answer.lower())

        processes_answer = answer_system_query(
            "what processes are using the most memory", metrics)
        self.assertIn("Busiest by memory", processes_answer)

        # An explicit monitor request still returns the full card.
        card = answer_system_query("monitor my system", metrics)
        self.assertIn("SYSTEM MONITOR", card)

    def test_top_processes_shape_and_limits(self):
        """The process helper returns bounded, well-formed rows."""
        rows = top_processes(3, by="memory")
        self.assertLessEqual(len(rows), 3)
        for row in rows:
            self.assertIn("pid", row)
            self.assertIn("name", row)
            self.assertIn("cpu_percent", row)
            self.assertIn("memory_percent", row)


    def test_bridge_answers_metric_questions_without_the_model(self):
        """Chat/voice questions are answered from metrics, not by the LLM."""
        answer = process_chat("what is my cpu usage")
        self.assertIn("CPU is at", answer)

        voice = process_voice_command("what is my cpu usage")
        self.assertEqual(voice.get("action"), "system_monitor_answer")
        self.assertIn("CPU is at", voice.get("response", ""))

        # An explicit monitor request keeps the panel-opening action.
        voice_card = process_voice_command("Monitor my system")
        self.assertEqual(voice_card.get("action"), "system_monitor")
        self.assertIn("metrics", voice_card)

    def test_stream_router_splits_static_from_ai(self):
        """Deterministic answers stay local; only real questions hit the model."""
        static = process_chat_stream("what is my cpu usage")
        self.assertEqual(static.get("kind"), "static")
        self.assertIn("CPU is at", static.get("data", ""))

        monitor = process_chat_stream("monitor my system")
        self.assertEqual(monitor.get("kind"), "static")
        self.assertEqual(monitor.get("monitor_topic"), "overall")

        ai = process_chat_stream("Tell me a short story about a robot")
        self.assertEqual(ai.get("kind"), "ai")
        self.assertEqual(ai.get("question"), "Tell me a short story about a robot")

        empty = process_chat_stream("   ")
        self.assertEqual(empty.get("kind"), "static")

    def test_broadcast_system_monitor_trigger_actually_broadcasts(self):
        """Regression: the broadcast body was lost in a merge, so voice
        activation never opened the dashboard panel."""
        metrics = get_system_metrics()
        with mock.patch.object(server_module, "broadcast_message_sync") as sender:
            server_module.broadcast_system_monitor_trigger(metrics)
        self.assertEqual(sender.call_count, 1)
        payload = sender.call_args[0][0]
        self.assertEqual(payload["type"], "show_system_monitor")
        self.assertIs(payload["data"], metrics)
        self.assertIn("SYSTEM MONITOR", payload["formatted"])

    def test_streaming_chat_sends_chunks(self):
        """chat + stream:true streams chat_chunk/chat_end (model stubbed)."""
        def fake_stream(question):
            yield "Hello"
            yield " world"

        client = TestClient(app)
        with mock.patch.object(server_module, "stream_ai", fake_stream):
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "chat", "data": "Say hi to me", "stream": True})
                messages = [ws.receive_json() for _ in range(3)]
        self.assertEqual([m["type"] for m in messages],
                         ["chat_chunk", "chat_chunk", "chat_end"])
        self.assertEqual(messages[0]["data"], "Hello")
        self.assertEqual(messages[2]["data"], "Hello world")

    def test_monitor_chat_opens_panel_and_question_does_not(self):
        """'Monitor my system' broadcasts the panel; a question only answers."""
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "chat", "data": "Monitor my system", "stream": True})
            first = ws.receive_json()
            second = ws.receive_json()
        types = {first["type"], second["type"]}
        self.assertIn("response", types)
        self.assertIn("show_system_monitor", types)
        response = first if first["type"] == "response" else second
        self.assertIn("SYSTEM MONITOR", response["data"])

        # A metric question is answered in the chat feed (no panel broadcast),
        # which the classifier guarantees by not returning 'overall'.
        self.assertNotEqual(classify_system_query("what is my cpu usage"), "overall")


def run_tests():
    """Run the test suite."""
    print("=" * 60)
    print("🧪 RUNNING ZYRA SYSTEM MONITOR TEST SUITE")
    print("=" * 60)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestSystemMonitor)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
