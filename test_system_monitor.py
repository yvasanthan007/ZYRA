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

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_monitor import (
    get_system_metrics,
    format_system_monitor_text,
    get_voice_summary,
    is_system_monitor_intent,
    start_system_monitor,
    make_progress_bar,
    format_bytes,
    format_speed,
    analyze_system_health,
    SystemMonitor,
)
from backend.zyra_bridge import (
    process_chat,
    process_command,
    process_voice_command,
    process_message,
    COMMAND_MAP,
)
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
