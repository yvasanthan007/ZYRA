# Shared state and controls for ZYRA's single desktop microphone pipeline.
from __future__ import annotations
import threading
import time
from typing import Any, Dict, Optional
_lock = threading.RLock()
_enabled = threading.Event()
_last_turn: Dict[str, Any] = {"id": 0, "transcript": "", "response": ""}
_state = "IDLE"
_error: Optional[str] = None

def configure_for_process(desktop: bool) -> None:
    # Keep legacy CLI listening; desktop microphone capture is opt-in.
    if not desktop:
        _enabled.set()


def set_enabled(enabled: bool) -> bool:
    global _state, _error
    with _lock:
        if enabled:
            _error = None
            _enabled.set()
            if _state in ("IDLE", "ERROR"):
                _state = "LISTENING"
        else:
            _enabled.clear()
            if _state != "ERROR":
                _state = "IDLE"
    return _enabled.is_set()


def is_enabled() -> bool:
    return _enabled.is_set()


def wait_until_enabled(shutdown_check, interval: float = 0.2) -> bool:
    while shutdown_check():
        if _enabled.wait(interval):
            return True
    return False

def update_state(state: str, error: Optional[str] = None) -> None:
    global _state, _error
    with _lock:
        if _enabled.is_set() or state == "IDLE":
            _state = state.upper()
            _error = error

def update_turn(transcript: Optional[str] = None, response: Optional[str] = None) -> Dict[str, Any]:
    with _lock:
        if transcript is not None:
            _last_turn["id"] += 1
            _last_turn["transcript"] = transcript
            _last_turn["response"] = ""
            _last_turn["updated_at"] = time.time()
        if response is not None:
            _last_turn["response"] = response
            _last_turn["updated_at"] = time.time()
        return dict(_last_turn)


def status() -> Dict[str, Any]:
    with _lock:
        return {
            "enabled": _enabled.is_set(),
            "state": _state if _enabled.is_set() or _state == "ERROR" else "IDLE",
            "error": _error,
            "turn": dict(_last_turn),
        }
