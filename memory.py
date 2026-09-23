"""
memory.py — ZYRA Long-Term Memory Store

Hardened persistence for Zyra's neural core:

  • Thread-safe — a reentrant lock guards every read-modify-write operation, so
    the voice loop, the FastAPI web API and the desktop bridge can remember and
    recall concurrently without corrupting each other.
  • Atomic writes — data is written to a temp file and then atomically moved
    into place (os.replace), so a crash mid-write can never truncate or corrupt
    the live memory file.
  • Corruption-resilient load — if the JSON store is somehow damaged, the broken
    file is backed up (memory/data.json.corrupt-<timestamp>) and an empty store
    is returned, so Zyra keeps working instead of crashing.
  • Path-resilient — the store location is resolved from this module's own path,
    so it works no matter which directory Zyra is launched from. An absolute
    path can also be forced with the ZYRA_MEMORY_FILE environment variable.

Public API (backward compatible with the legacy module):
    load_memory(), save_memory(data)
    remember(key, value), recall(key), forget(key)
    remember_many(pairs), all_memory(), clear_memory(), stats()
"""

import datetime
import json
import os
import tempfile
import threading
from typing import Any, Dict, Optional


_MEMORY_LOCK = threading.RLock()

_DEFAULT_MEMORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "memory",
    "data.json",
)


def memory_file_path() -> str:
    """Resolve the memory store location (env override trumps the default)."""
    override = os.environ.get("ZYRA_MEMORY_FILE")
    if override:
        return os.path.abspath(override)
    return _DEFAULT_MEMORY_FILE


MEMORY_FILE = memory_file_path()


def _ensure_dir_exists(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass


def _load_unlocked() -> Dict[str, Any]:
    """Read and parse the store. Callers must already hold _MEMORY_LOCK."""
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(
                f"memory root is {type(data).__name__}, expected dict"
            )
        return data
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        # Back up the damaged file (never destroy evidence) and start fresh so
        # the assistant keeps working instead of crashing on every recall.
        try:
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = f"{MEMORY_FILE}.corrupt-{stamp}"
            os.replace(MEMORY_FILE, backup)
            print(f"memory: repaired damaged store -> {backup} ({exc})")
        except OSError:
            pass
        return {}


def _save_unlocked(data: Dict[str, Any]) -> None:
    """Atomically persist the store. Callers must already hold _MEMORY_LOCK."""
    _ensure_dir_exists(MEMORY_FILE)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix="zyra_memory_",
        dir=os.path.dirname(MEMORY_FILE),
        suffix=".json",
    )
    try:
        # Write via the already-open file descriptor, then atomically replace.
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data or {}, fh, ensure_ascii=False, indent=4)
        os.replace(tmp_path, MEMORY_FILE)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def load_memory() -> Dict[str, Any]:
    """Return a snapshot copy of the whole store ({} if missing/damaged)."""
    with _MEMORY_LOCK:
        return dict(_load_unlocked())


def save_memory(data: Dict[str, Any]) -> None:
    """Persist a complete memory dict atomically."""
    with _MEMORY_LOCK:
        _save_unlocked(dict(data or {}))


def remember(key: str, value: Any) -> None:
    """Store a single fact. `value` must be JSON-serializable."""
    with _MEMORY_LOCK:
        data = _load_unlocked()
        data[key] = value
        _save_unlocked(data)


def recall(key: str) -> Optional[Any]:
    """Fetch a stored fact (None when it does not exist)."""
    with _MEMORY_LOCK:
        return _load_unlocked().get(key)


def forget(key: str) -> bool:
    """Remove a fact. Returns True if the key existed."""
    with _MEMORY_LOCK:
        data = _load_unlocked()
        if key not in data:
            return False
        del data[key]
        _save_unlocked(data)
        return True


def remember_many(pairs: Dict[str, Any]) -> None:
    """Store several facts in a single atomic write."""
    if not pairs:
        return
    with _MEMORY_LOCK:
        data = _load_unlocked()
        data.update(pairs)
        _save_unlocked(data)


def all_memory() -> Dict[str, Any]:
    """Alias of load_memory() — a snapshot copy of every fact."""
    return load_memory()


def clear_memory() -> None:
    """Wipe the store back to an empty dict."""
    with _MEMORY_LOCK:
        _save_unlocked({})


def stats() -> Dict[str, Any]:
    """Small diagnostic payload for health checks / dashboards."""
    data = load_memory()
    return {
        "file": MEMORY_FILE,
        "facts": len(data),
        "keys": sorted(str(k) for k in data.keys())[:50],
    }


if __name__ == "__main__":
    # Minimal self-test (no external dependencies).
    remember("test_key", {"answer": 42})
    print("recall:", recall("test_key"))
    print("forget:", forget("test_key"))
    print("stats:", stats())