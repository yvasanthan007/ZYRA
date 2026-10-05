"""
backend/agent_tools.py — ZYRA safe agent tool layer.

A small, explicit tool registry used by the bridge for JARVIS-like actions:
open applications/folders/files, search files, browser search, screenshots,
system info, and guarded destructive actions. Every tool declares a safety
level; SENSITIVE/DANGEROUS tools require explicit confirmation.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List

SAFE = "SAFE"
SENSITIVE = "SENSITIVE"
DANGEROUS = "DANGEROUS"

_HOME = Path.home()
_SEARCH_ROOTS = [
    _HOME / "Desktop",
    _HOME / "Documents",
    _HOME / "Downloads",
    _HOME / "OneDrive" / "Desktop",
    _HOME / "OneDrive" / "Documents",
]
_FILE_EXTS = {
    "presentation": (".ppt", ".pptx", ".odp", ".key"),
    "document": (".doc", ".docx", ".pdf", ".txt", ".md", ".rtf"),
    "spreadsheet": (".xls", ".xlsx", ".csv"),
    "image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"),
    "video": (".mp4", ".mkv", ".avi", ".mov"),
    "audio": (".mp3", ".wav", ".m4a", ".flac"),
    "code": (".py", ".js", ".ts", ".tsx", ".html", ".css", ".json"),
}

_pending_confirmations: Dict[str, Dict[str, Any]] = {}


def _ok(message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": True, "message": message, **extra}


def _fail(message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "message": message, **extra}


def _launch(path_or_cmd: str) -> None:
    os.startfile(path_or_cmd)  # type: ignore[attr-defined]


def open_application(name: str = "", **_: Any) -> Dict[str, Any]:
    from commands.open_app import (
        open_chrome, open_vscode, open_notepad, open_calculator,
        open_cmd, open_powershell, open_task_manager, open_file_explorer,
    )

    key = (name or "").lower().strip()
    mapping: Dict[str, Callable[[], Any]] = {
        "chrome": open_chrome, "google chrome": open_chrome,
        "vs code": open_vscode, "vscode": open_vscode,
        "visual studio code": open_vscode,
        "notepad": open_notepad, "calculator": open_calculator,
        "cmd": open_cmd, "command prompt": open_cmd,
        "powershell": open_powershell,
        "task manager": open_task_manager,
        "explorer": open_file_explorer, "file explorer": open_file_explorer,
    }
    fn = mapping.get(key)
    if fn:
        fn()
        return _ok(f"Opening {name}.")
    try:
        subprocess.Popen(["cmd", "/c", "start", "", name], shell=False)
        return _ok(f"Opening {name}.")
    except Exception as exc:
        return _fail(f"I couldn't open {name}: {exc}")


def close_application(name: str = "", **_: Any) -> Dict[str, Any]:
    from commands.close_app import close_app
    if not name:
        return _fail("Tell me which application to close.")
    return _ok(str(close_app(name)))


def open_folder(path: str = "", **_: Any) -> Dict[str, Any]:
    target = Path(os.path.expandvars(path or "")).expanduser()
    if not target.exists() or not target.is_dir():
        return _fail(f"I couldn't find the folder {path}.")
    _launch(str(target))
    return _ok(f"Opened {target}.", path=str(target))


def open_file(path: str = "", **_: Any) -> Dict[str, Any]:
    target = Path(os.path.expandvars(path or "")).expanduser()
    if not target.exists() or not target.is_file():
        return _fail(f"I couldn't find the file {path}.")
    _launch(str(target))
    return _ok(f"Opened {target.name}.", path=str(target))


def _iter_search_roots() -> List[Path]:
    return [p for p in _SEARCH_ROOTS if p.exists()]


def search_files(query: str = "", kind: str = "", limit: int = 8, **_: Any) -> Dict[str, Any]:
    q = (query or "").lower().strip()
    if not q and not kind:
        return _fail("Tell me what file to look for.")
    exts = _FILE_EXTS.get(kind.lower(), ())
    matches: List[Dict[str, Any]] = []
    deadline = time.time() + float(os.environ.get("ZYRA_SEARCH_TIMEOUT_S", "12"))
    max_depth = int(os.environ.get("ZYRA_SEARCH_MAX_DEPTH", "6"))
    scanned = 0
    for root in _iter_search_roots():
        root_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            if time.time() > deadline or scanned > 60000:
                break
            # Prune deep trees and heavy/irrelevant folders.
            depth = len(Path(dirpath).parts) - root_depth
            if depth >= max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [
                d for d in dirnames
                if d not in ("node_modules", ".git", ".venv", "__pycache__",
                             ".build", "AppData", "$Recycle.Bin")
                and not d.startswith(".")
            ]
            for fname in filenames:
                scanned += 1
                if exts and not fname.lower().endswith(exts):
                    continue
                if q and q not in fname.lower():
                    continue
                p = Path(dirpath) / fname
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    mtime = 0
                matches.append({"path": str(p), "name": fname, "modified": mtime})
                if len(matches) >= 200:
                    break
        if time.time() > deadline:
            break
    matches.sort(key=lambda m: m["modified"], reverse=True)
    matches = matches[: max(1, int(limit))]
    if not matches:
        return _fail(f"I couldn't find any {kind or 'file'} matching '{query}'.")
    return _ok(f"I found {len(matches)} match(es).", matches=matches)


def find_and_open_file(query: str = "", kind: str = "", **kwargs: Any) -> Dict[str, Any]:
    result = search_files(query=query, kind=kind, limit=1)
    if not result.get("success"):
        return result
    path = result["matches"][0]["path"]
    opened = open_file(path=path)
    opened["matches"] = result["matches"]
    return opened


def browser_search(query: str = "", engine: str = "google", **_: Any) -> Dict[str, Any]:
    if not query:
        return _fail("Tell me what to search for.")
    from commands.open_app import search_google, search_youtube
    if engine.lower() == "youtube":
        search_youtube(query)
        return _ok(f"Searching YouTube for {query}.")
    search_google(query)
    return _ok(f"Searching Google for {query}.")


def browser_open(url: str = "", **_: Any) -> Dict[str, Any]:
    if not url:
        return _fail("Tell me which website to open.")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    webbrowser.open(url)
    return _ok(f"Opening {url}.")


def take_screenshot(**_: Any) -> Dict[str, Any]:
    from commands.open_app import screenshot
    screenshot()
    return _ok("Screenshot captured.")


def system_information(**_: Any) -> Dict[str, Any]:
    from system_monitor import get_system_metrics, format_system_monitor_text
    metrics = get_system_metrics()
    return _ok(format_system_monitor_text(metrics), metrics=metrics)


def delete_file(path: str = "", confirmed: bool = False, **_: Any) -> Dict[str, Any]:
    target = Path(os.path.expandvars(path or "")).expanduser()
    if not target.exists() or not target.is_file():
        return _fail(f"I couldn't find the file {path}.")
    if not confirmed:
        token = f"delete:{target}"
        _pending_confirmations[token] = {
            "tool": "delete_file", "path": str(target), "time": time.time(),
        }
        return {
            "success": False,
            "requires_confirmation": True,
            "confirmation_token": token,
            "message": (
                f"Deleting {target} is destructive. "
                "Say 'confirm delete' to proceed."
            ),
        }
    try:
        target.unlink()
        return _ok(f"Deleted {target}.")
    except Exception as exc:
        return _fail(f"I couldn't delete {target}: {exc}")


def confirm(token: str = "") -> Dict[str, Any]:
    pending = _pending_confirmations.pop(token, None)
    if not pending:
        return _fail("There is no pending action to confirm.")
    if pending["tool"] == "delete_file":
        return delete_file(path=pending["path"], confirmed=True)
    return _fail("Unsupported confirmation.")


TOOLS: Dict[str, Dict[str, Any]] = {
    "open_application": {"fn": open_application, "safety": SAFE},
    "close_application": {"fn": close_application, "safety": SENSITIVE},
    "open_folder": {"fn": open_folder, "safety": SAFE},
    "open_file": {"fn": open_file, "safety": SAFE},
    "search_files": {"fn": search_files, "safety": SAFE},
    "find_and_open_file": {"fn": find_and_open_file, "safety": SAFE},
    "browser_search": {"fn": browser_search, "safety": SAFE},
    "browser_open": {"fn": browser_open, "safety": SAFE},
    "take_screenshot": {"fn": take_screenshot, "safety": SAFE},
    "system_information": {"fn": system_information, "safety": SAFE},
    "delete_file": {"fn": delete_file, "safety": DANGEROUS},
}


def execute_tool(name: str, **kwargs: Any) -> Dict[str, Any]:
    tool = TOOLS.get(name)
    if not tool:
        return _fail(f"Unknown tool: {name}")
    try:
        return tool["fn"](**kwargs)
    except Exception as exc:
        return _fail(f"{name} failed: {exc}")
