"""
backend/url_analyzer/history.py — Recent URL scan history

Lightweight JSON persistence for the "RECENT URL SCANS" section of the
URL Analyzer panel. Keeps the full analysis result of the last N scans so
previous analyses can be reopened from the dashboard.

Storage: backend/url_analyzer/url_scan_history.json (created on demand).
"""

import json
import os
import threading
from datetime import datetime

_MAX_ENTRIES = 25

_LOCK = threading.Lock()
_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "url_scan_history.json"
)


def _load_unlocked() -> list:
    try:
        with open(_HISTORY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_unlocked(entries: list) -> None:
    try:
        with open(_HISTORY_PATH, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass  # history is best-effort; never break a scan over it


def add_entry(result: dict) -> None:
    """Store a completed scan result at the top of the history."""
    if not result or not result.get("success"):
        return
    entry = {
        "scan_id": result.get("scan_id"),
        "url": result.get("url"),
        "domain": result.get("domain_display") or result.get("hostname"),
        "score": result.get("score"),
        "risk_level": result.get("risk_level"),
        "risk_level_label": result.get("risk_level_label"),
        "classification": result.get("classification"),
        "classification_label": result.get("classification_label"),
        "timestamp": result.get("timestamp"),
        "timestamp_display": result.get("timestamp_display"),
        "result": result,
    }
    with _LOCK:
        entries = [e for e in _load_unlocked()
                   if e.get("scan_id") != entry["scan_id"]]
        entries.insert(0, entry)
        _save_unlocked(entries[:_MAX_ENTRIES])


def recent(limit: int = 8) -> list:
    """Most recent scan summaries (without the heavy result payloads)."""
    with _LOCK:
        entries = _load_unlocked()
    out = []
    for e in entries[: max(0, int(limit))]:
        out.append({k: v for k, v in e.items() if k != "result"})
    return out


def find(scan_id: str):
    """Return the full stored result for a scan_id, or None."""
    if not scan_id:
        return None
    with _LOCK:
        entries = _load_unlocked()
    for e in entries:
        if e.get("scan_id") == scan_id:
            return e.get("result")
    return None


def entry_count() -> int:
    with _LOCK:
        return len(_load_unlocked())


def _now_display() -> str:
    return datetime.now().strftime("%d %b %Y")


_ = datetime  # namespace stability
