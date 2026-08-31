"""
backend/dns_lookup/history.py — Recent DNS lookup history

Lightweight JSON persistence for the "RECENT DNS LOOKUPS" section of the
DNS Lookup panel. Keeps the full result of the last N lookups so previous
analyses can be reopened from the dashboard.

Storage: backend/dns_lookup/dns_lookup_history.json (created on demand).
"""

import json
import os
import threading

_MAX_ENTRIES = 25

_LOCK = threading.Lock()
_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dns_lookup_history.json"
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
        pass  # history is best-effort; never break a lookup over it


def add_entry(result: dict) -> None:
    """Store a completed lookup result at the top of the history."""
    if not result or not result.get("success"):
        return
    entry = {
        "lookup_id": result.get("lookup_id"),
        "domain": result.get("domain_display") or result.get("domain"),
        "status": result.get("status"),
        "score": result.get("score"),
        "risk_level": result.get("risk_level"),
        "risk_level_label": result.get("risk_level_label"),
        "response_time_ms": result.get("response_time_ms"),
        "dnssec": (result.get("dnssec") or {}).get("status"),
        "timestamp": result.get("timestamp"),
        "timestamp_display": result.get("timestamp_display"),
        "result": result,
    }
    with _LOCK:
        entries = [e for e in _load_unlocked()
                   if e.get("lookup_id") != entry["lookup_id"]]
        entries.insert(0, entry)
        _save_unlocked(entries[:_MAX_ENTRIES])


def recent(limit: int = 8) -> list:
    """Most recent lookup summaries (without the heavy result payloads)."""
    with _LOCK:
        entries = _load_unlocked()
    out = []
    for e in entries[: max(0, int(limit))]:
        out.append({k: v for k, v in e.items() if k != "result"})
    return out


def find(lookup_id: str):
    """Return the full stored result for a lookup_id, or None."""
    if not lookup_id:
        return None
    with _LOCK:
        entries = _load_unlocked()
    for e in entries:
        if e.get("lookup_id") == lookup_id:
            return e.get("result")
    return None
