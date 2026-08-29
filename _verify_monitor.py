"""
Temporary live verification for the System Monitor feature additions.
Covers: WS reply typing fix, chat-intent broadcast, sustained analysis.
Not part of the project test suite — deleted after verification.
"""
import sys
import os
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from backend.server import app
from system_monitor import analyze_system_health, get_system_metrics, SystemMonitor


def test_ws_system_metrics_reply_type():
    """WS system_metrics request must reply with type 'system_metrics' (not 'response')."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "system_metrics", "data": None})
        msg = ws.receive_json()
        assert msg.get("type") == "system_metrics", f"expected system_metrics, got {msg.get('type')}"
        assert msg.get("success") is True
        assert "cpu" in msg.get("data", {}), "data should contain cpu"
    print("  PASS: WS system_metrics reply type")


def test_ws_chat_monitor_broadcast():
    """Chat 'Monitor my system' must return the card AND broadcast show_system_monitor."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "data": "Monitor my system"})
        resp = ws.receive_json()
        assert resp.get("type") == "response", f"expected response, got {resp.get('type')}"
        assert "SYSTEM MONITOR" in resp.get("data", ""), "response should contain the card"
        broadcast = ws.receive_json()
        assert broadcast.get("type") == "show_system_monitor", f"expected show_system_monitor, got {broadcast.get('type')}"
        assert "cpu" in broadcast.get("data", {}), "broadcast data should contain cpu"
    print("  PASS: WS chat monitor broadcast")


def test_ws_chat_normal_not_broadcast():
    """A normal chat message must NOT trigger a show_system_monitor broadcast."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "data": "hello there"})
        resp = ws.receive_json()
        assert resp.get("type") == "response"
        assert resp.get("type") != "show_system_monitor"
    print("  PASS: WS chat normal no broadcast")


def test_sustained_cpu_warning():
    """Sustained high CPU (current below 90 but history high) triggers extended-period WARNING."""
    hist = deque([{"cpu": 95.0, "ram": 50.0} for _ in range(8)], maxlen=40)
    # current 87% is below the 90% immediate threshold, but history is sustained high
    res = analyze_system_health(87.0, 50.0, 40.0, history=hist)
    assert res["status"] == "WARNING", f"expected WARNING, got {res['status']}"
    assert "extended period" in res["description"], f"expected 'extended period' in description, got {res['description']}"
    assert res.get("sustained") is True
    print("  PASS: sustained CPU warning")


def test_sustained_ram_warning():
    """Sustained high RAM (current below 92 but history high) triggers extended-period WARNING."""
    hist = deque([{"cpu": 30.0, "ram": 95.0} for _ in range(8)], maxlen=40)
    # current 89% is below the 92% immediate threshold, but history is sustained high
    res = analyze_system_health(30.0, 89.0, 40.0, history=hist)
    assert res["status"] == "WARNING"
    assert "extended period" in res["description"]
    assert res.get("sustained") is True
    print("  PASS: sustained RAM warning")


def test_no_history_unchanged():
    """Without history, instantaneous analysis is preserved (backward-compat)."""
    norm = analyze_system_health(50.0, 55.0, 50.0)
    assert norm["status"] == "NORMAL"
    assert norm.get("sustained") is False
    high = analyze_system_health(80.0, 50.0, 40.0)
    assert high["status"] == "HIGH RESOURCE USAGE"
    print("  PASS: no-history analysis unchanged")


def test_history_accumulates():
    """SystemMonitor.get_metrics accumulates a rolling history window."""
    mon = SystemMonitor()
    for _ in range(5):
        mon.get_metrics()
    assert len(mon._history) == 5, f"expected 5 samples, got {len(mon._history)}"
    assert mon._history.maxlen == 40
    print("  PASS: history accumulates")


def test_metrics_has_sustained_field():
    """get_metrics returns the sustained flag in analysis."""
    m = get_system_metrics()
    assert "sustained" in m.get("analysis", {}), "analysis should contain 'sustained'"
    print("  PASS: metrics has sustained field")


if __name__ == "__main__":
    print("LIVE VERIFICATION — System Monitor additions")
    test_ws_system_metrics_reply_type()
    test_ws_chat_monitor_broadcast()
    test_ws_chat_normal_not_broadcast()
    test_sustained_cpu_warning()
    test_sustained_ram_warning()
    test_no_history_unchanged()
    test_history_accumulates()
    test_metrics_has_sustained_field()
    print("\nALL LIVE CHECKS PASSED")