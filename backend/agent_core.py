"""
backend/agent_core.py — ZYRA agent core (intent → plan → tools → observe).

Sits between the bridge and the tool layer. Understands natural requests,
splits multi-step commands ("open X, find the presentation, then check this
URL"), executes each step through the safe tool registry, tracks context so
follow-ups like "now open the presentation" resolve against recent state,
and falls back to the AI brain for plain conversation.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from backend.agent_tools import execute_tool, confirm as confirm_pending

# ── Conversation / task context (per-process, lightweight) ──────────────
_context: Dict[str, Any] = {
    "last_files": [],        # recent file matches (for "the presentation")
    "last_folder": None,     # last opened folder (for "my project")
    "last_url": None,        # last analyzed/opened URL
    "last_tool": None,
    "updated": 0.0,
}


def get_context() -> Dict[str, Any]:
    return dict(_context)


def _touch() -> None:
    _context["updated"] = time.time()


_SPLIT_RE = re.compile(r"\s*(?:,?\s+and then\s+|,?\s+then\s+|,?\s+and\s+|;\s*)\s*", re.I)
_URL_RE = re.compile(r"(https?://\S+|www\.\S+|\b[\w-]+\.(?:com|net|org|io|xyz|top|tk|ml|ga|cf|dev|app|ai|in|co)(?:/\S*)?)", re.I)


def _split_steps(text: str) -> List[str]:
    parts = [p.strip(" .,") for p in _SPLIT_RE.split(text) if p.strip(" .,")]
    return parts or [text]


def _resolve_file_reference(step: str) -> Optional[Dict[str, str]]:
    """Resolve 'the presentation' / 'it' against recent file context."""
    lowered = step.lower()
    if any(w in lowered for w in ("presentation", "slides", "ppt")):
        for f in _context.get("last_files", []):
            if f["name"].lower().endswith((".ppt", ".pptx", ".odp")):
                return f
        return {"__kind__": "presentation"}
    if re.search(r"\b(it|that file|the file)\b", lowered) and _context.get("last_files"):
        return _context["last_files"][0]
    return None


def _run_step(step: str) -> Dict[str, Any]:
    """Execute one natural-language step. Returns {handled, message, ...}."""
    s = step.strip()
    low = s.lower()

    # Confirmation of a pending destructive action
    if low in ("confirm delete", "yes delete", "confirm", "yes, delete it"):
        res = confirm_pending(_context.get("pending_token", ""))
        return {"handled": True, "message": res["message"], "result": res}

    # URL security analysis
    url_match = _URL_RE.search(s)
    if url_match and any(k in low for k in ("check", "analy", "safe", "suspicious", "scan", "explain")):
        from backend.link_security import analyze_url_security, format_security_report
        url = url_match.group(0)
        _context["last_url"] = url
        _touch()
        report = format_security_report(analyze_url_security(url))
        return {"handled": True, "message": report, "action": "link_analysis"}

    # Open project / folder
    m = re.search(r"open (?:my |the )?([\w .-]*?(?:project|folder|directory))\b", low)
    if m:
        name = m.group(1).strip() or "project"
        from backend.agent_tools import search_files
        # Try known folder first, then search for a matching directory
        res = execute_tool("open_folder", path=_context.get("last_folder") or "")
        if not res.get("success"):
            search = execute_tool("search_files", query=name.replace("project", "").strip() or name)
            if search.get("success"):
                from pathlib import Path
                folder = str(Path(search["matches"][0]["path"]).parent)
                res = execute_tool("open_folder", path=folder)
        if res.get("success"):
            _context["last_folder"] = res.get("path")
            _touch()
        return {"handled": True, "message": res["message"], "result": res}

    # Find / open a file (presentation, document, named file)
    m = re.search(r"(?:find|open|locate)\s+(?:the\s+|my\s+)?([\w .-]+?)(?:\s+file)?$", low)
    if m and any(k in low for k in ("find", "open", "locate", "presentation", "file")):
        query = m.group(1).strip()
        ref = _resolve_file_reference(low)
        kind = ""
        if ref and ref.get("__kind__"):
            kind = "presentation"
            query = ""
        elif ref:
            res = execute_tool("open_file", path=ref["path"])
            return {"handled": True, "message": res["message"], "result": res}
        if any(w in low for w in ("presentation", "slides", "ppt")):
            kind = "presentation"
        res = execute_tool("find_and_open_file", query=query, kind=kind)
        if res.get("success") and res.get("matches"):
            _context["last_files"] = res["matches"]
            _touch()
        return {"handled": True, "message": res["message"], "result": res}

    # Browser search
    m = re.search(r"search (?:for )?(.+)", low)
    if m:
        query = m.group(1).strip()
        res = execute_tool("browser_search", query=query)
        return {"handled": True, "message": res["message"], "result": res}

    # Open an application
    m = re.search(r"open\s+([\w .-]+)", low)
    if m:
        name = m.group(1).strip()
        res = execute_tool("open_application", name=name)
        if res.get("success"):
            return {"handled": True, "message": res["message"], "result": res}

    # Close an application
    m = re.search(r"close\s+([\w .-]+)", low)
    if m:
        res = execute_tool("close_application", name=m.group(1).strip())
        return {"handled": True, "message": res["message"], "result": res}

    # Delete file (guarded)
    m = re.search(r"delete\s+(?:the\s+)?(?:file\s+)?(.+)", low)
    if m:
        target = m.group(1).strip()
        ref = _resolve_file_reference(target)
        path = ref["path"] if ref and ref.get("path") else target
        res = execute_tool("delete_file", path=path)
        if res.get("confirmation_token"):
            _context["pending_token"] = res["confirmation_token"]
            _touch()
        return {"handled": True, "message": res["message"], "result": res}

    # Screenshot / system info
    if "screenshot" in low:
        res = execute_tool("take_screenshot")
        return {"handled": True, "message": res["message"], "result": res}

    return {"handled": False}


def run_agent(text: str) -> Dict[str, Any]:
    """
    Main entry: understand → plan → execute → observe → respond.
    Returns {"handled": bool, "response": str, "steps": [...]}.
    When handled is False the caller should fall back to the AI brain.
    """
    if not text or not text.strip():
        return {"handled": False}

    steps = _split_steps(text)
    results: List[Dict[str, Any]] = []
    messages: List[str] = []
    any_handled = False

    for step in steps:
        outcome = _run_step(step)
        results.append({"step": step, **outcome})
        if outcome.get("handled"):
            any_handled = True
            if outcome.get("message"):
                messages.append(outcome["message"])
        else:
            # Unhandled step in a multi-step request: report it honestly.
            if len(steps) > 1:
                messages.append(f"I wasn't sure how to handle '{step}'.")

    if not any_handled:
        return {"handled": False}

    return {
        "handled": True,
        "response": "\n\n".join(messages) if messages else "Done.",
        "steps": results,
    }
