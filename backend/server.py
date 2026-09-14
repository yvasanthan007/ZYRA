"""
FastAPI Backend Server for ZYRA AI Assistant
Serves the desktop dashboard and provides API/WebSocket endpoints for Zyra
"""
import os
import sys
import json
import time
import asyncio
import threading
import webbrowser
from typing import Optional, Dict, Any
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

# Add parent directory to path for importing Zyra modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.zyra_bridge import (
    process_chat,
    process_command,
    process_voice_command,
    process_message,
    speak_text,
)
from backend.link_security import (
    analyze_url_security,
    format_security_report,
    extract_url,
)
from system_monitor import (
    get_system_metrics,
    format_system_monitor_text,
    get_voice_summary,
    is_system_monitor_intent,
    start_system_monitor,
)
from nmap_handler import is_nmap_intent
from backend.nmap_service import (
    SCAN_OPERATIONS,
    build_nmap_command,
    extract_target,
    get_result,
    nmap_available,
    resolve_operation,
    run_scan,
    validate_target,
)
from backend.nmap_report import (
    build_report_data,
    report_to_json,
    report_to_pdf,
    report_to_text,
)
from backend.url_analyzer import (
    SCAN_STAGES,
    build_chat_ack,
    build_report_data as url_build_report_data,
    build_voice_summary,
    extract_target_url,
    get_history,
    get_last_scan,
    get_scan_state,
    is_url_analysis_intent,
    report_filename,
    report_to_pdf as url_report_to_pdf,
    report_to_text as url_report_to_text,
    start_scan,
)
from backend.dns_lookup import (
    DNS_STAGES,
    build_chat_ack as dns_build_chat_ack,
    build_voice_summary as dns_build_voice_summary,
    build_dns_report_data as dns_build_report_data,
    dns_history_recent,
    dns_report_filename,
    dns_report_to_pdf,
    dns_report_to_text,
    extract_dns_record_type,
    extract_dns_target,
    get_dns_lookup,
    get_dns_server_info,
    get_scan_state as get_dns_scan_state,
    is_dns_intent,
    start_dns_lookup,
)

app = FastAPI(
    title="ZYRA AI Assistant API",
    description="Backend API for ZYRA - Your AI Desktop Assistant",
    version="1.0.0",
)

# CORS middleware - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dashboard directory
DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "desktop-dashboard")

# WebSocket connection manager
class ConnectionManager:
    """Manages WebSocket connections for real-time communication"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """Send a message to all connected clients"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

    async def send_personal(self, message: Dict[str, Any], websocket: WebSocket):
        """Send a message to a specific client"""
        try:
            await websocket.send_json(message)
        except Exception:
            pass

manager = ConnectionManager()

# Event loop reference for thread-safe cross-thread broadcasting
_server_loop: Optional[asyncio.AbstractEventLoop] = None


@app.on_event("startup")
async def on_startup():
    global _server_loop
    _server_loop = asyncio.get_running_loop()


def broadcast_message_sync(message: Dict[str, Any]) -> None:
    """Thread-safe helper to broadcast a message to all connected clients."""
    global _server_loop
    if _server_loop and _server_loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(manager.broadcast(message), _server_loop)
        except Exception:
            pass


def broadcast_system_monitor_trigger(metrics: Optional[Dict[str, Any]] = None) -> None:
    """Broadcast system monitor activation to all connected clients."""
    if metrics is None:
        metrics = get_system_metrics()
# ========== Nmap Scan Manager ==========
# Runs scans in background threads (Nmap can take minutes), tracks live status,
# and broadcasts progress to the dashboard over WebSocket.

_nmap_lock = threading.Lock()
_nmap_active: Optional[Dict[str, Any]] = None
_nmap_last: Optional[Dict[str, Any]] = None
_nmap_last_error: Optional[str] = None

_NMAP_STAGE_PROGRESS = {
    "initializing": 8,
    "scanning": 45,
    "parsing results": 80,
    "analyzing": 90,
    "complete": 100,
    "error": 100,
}


def _nmap_public_state(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Strip non-serializable internals before sending scan state to clients."""
    if not state:
        return None
    return {k: v for k, v in state.items() if not k.startswith("_")}


def _nmap_set_state(**updates: Any) -> None:
    """Update the active scan state and broadcast it to all dashboard clients."""
    snapshot = None
    with _nmap_lock:
        if _nmap_active is None:
            return
        _nmap_active.update(updates)
        stage = str(_nmap_active.get("stage", "")).lower()
        if stage in _NMAP_STAGE_PROGRESS:
            _nmap_active["progress"] = _NMAP_STAGE_PROGRESS[stage]
        snapshot = _nmap_public_state(_nmap_active)
    if snapshot:
        broadcast_message_sync({"type": "nmap_status", "data": snapshot})


def _nmap_run_worker(scan_id: str, operation_key: str, target: str,
                     ports: Optional[str], request_text: str) -> None:
    """Background worker executing the whitelisted Nmap operation."""
    global _nmap_active, _nmap_last
    try:
        command = build_nmap_command(operation_key, target, ports=ports)
        _nmap_set_state(stage="scanning", command=command)

        result = run_scan(operation_key, target, ports=ports,
                          request_text=request_text)

        if not result.get("success"):
            err = result.get("error") or result.get("message") or "Scan failed."
            with _nmap_lock:
                if _nmap_active is not None:
                    _nmap_active.update(status="ERROR", stage="error",
                                        error=err, progress=100)
                    snapshot = _nmap_public_state(_nmap_active)
                    _nmap_active = None
                else:
                    snapshot = None
            broadcast_message_sync({"type": "nmap_status", "data": snapshot})
            broadcast_message_sync({
                "type": "nmap_error",
                "data": {"reason": err, "command": command},
            })
            return

        hosts = result.get("hosts", [])
        total_ports = result.get("open_ports_count",
                                 sum(len(h.get("ports", [])) for h in hosts))
        services = set()
        for h in hosts:
            for p in h.get("ports", []):
                if p.get("service"):
                    services.add(str(p["service"]).lower())
        summary_text = result.get("summary") or ""
        if not isinstance(summary_text, str):
            summary_text = ""
        hosts_up = result.get("hosts_count", len(hosts))
        chat_response = result.get("chat_response") or (
            f"Network scan completed. I discovered {hosts_up} active host(s) and "
            f"{total_ports} open port(s). I've displayed the detailed results in "
            "the Nmap Scanner panel, where you can generate or download the "
            "full report."
        )

        with _nmap_lock:
            if _nmap_active is not None:
                _nmap_active.update({
                    "status": "COMPLETE",
                    "stage": "complete",
                    "progress": 100,
                    "scan_id": result.get("scan_id"),
                    "command": result.get("command", command),
                    "chat_response": chat_response,
                    "summary": {
                        "hosts_up": hosts_up,
                        "hosts_total": hosts_up,
                        "open_ports": total_ports,
                        "services": len(services),
                    },
                    "hosts": hosts,
                    "observations": result.get("observations", []),
                    "analysis": result.get("analysis", {}),
                    "finished_at": time.time(),
                })
                snapshot = _nmap_public_state(_nmap_active)
                _nmap_last = dict(_nmap_active)
                _nmap_active = None
            else:
                snapshot = None
        broadcast_message_sync({"type": "nmap_status", "data": snapshot})

    except Exception as e:  # Never let the thread die silently
        with _nmap_lock:
            if _nmap_active is not None:
                _nmap_active.update(status="ERROR", stage="error",
                                    error=str(e), progress=100)
                snapshot = _nmap_public_state(_nmap_active)
                _nmap_active = None
            else:
                snapshot = None
        if snapshot:
            broadcast_message_sync({"type": "nmap_status", "data": snapshot})
        broadcast_message_sync({"type": "nmap_error", "data": {"reason": str(e)}})


# ========== REST API Endpoints ==========


def start_nmap_scan(operation_key: str, target: str, ports: Optional[str] = None,
                    request_text: str = "") -> Dict[str, Any]:
    """
    Validate parameters and launch a background Nmap scan.

    Returns a dict with success flag; on failure includes a user-facing error.
    """
    global _nmap_active

    if operation_key not in SCAN_OPERATIONS:
        return {"success": False,
                "error": f"Unknown scan operation: '{operation_key}'. Valid: {', '.join(sorted(SCAN_OPERATIONS))}"}

    valid, msg = validate_target(target)
    if not valid:
        return {"success": False, "error": msg}

    if ports is not None:
        ports = str(ports).strip() or None
        if ports and not all(p.strip().isdigit() or "-" in p for p in ports.split(",")):
            return {"success": False, "error": f"Invalid port specification: '{ports}'"}

    with _nmap_lock:
        if _nmap_active is not None:
            return {"success": False,
                    "error": "A scan is already running. Wait for it to complete or check its status in the Nmap panel."}

        avail = nmap_available()
        if not avail.get("available"):
            return {"success": False,
                    "error": ("Nmap is not installed or cannot be located. "
                              "Install Nmap and ensure the 'nmap' executable is on your system PATH."),
                    "error_kind": "nmap_missing"}

        meta = SCAN_OPERATIONS[operation_key]
        scan_id = f"nmap_{int(time.time() * 1000)}"
        command = build_nmap_command(operation_key, target, ports=ports)
        _nmap_active = {
            "scan_id": scan_id,
            "operation": operation_key,
            "operation_label": meta["label"],
            "request": request_text or meta["label"],
            "target": target,
            "ports": ports,
            "command": command,
            "status": "SCANNING",
            "stage": "initializing",
            "progress": 8,
            "started_at": time.time(),
        }
        snapshot = _nmap_public_state(_nmap_active)

    broadcast_message_sync({"type": "nmap_status", "data": snapshot})

    threading.Thread(
        target=_nmap_run_worker,
        args=(scan_id, operation_key, target, ports, request_text),
        daemon=True,
        name=f"ZYRA-Nmap-{scan_id}",
    ).start()
    return {"success": True, "scan_id": scan_id, "command": command}


def get_nmap_state() -> Dict[str, Any]:
    """Current Nmap module state for the dashboard (active scan or last result)."""
    with _nmap_lock:
        active = _nmap_public_state(_nmap_active)
        last = _nmap_public_state(_nmap_last)
    avail = nmap_available()
    return {
        "nmap_available": bool(avail.get("available")),
        "nmap_version": avail.get("version", "unknown"),
        "active": active,
        "last": last,
        "operations": {
            key: {
                "label": meta["label"],
                "description": meta.get("description", ""),
                "default_target": meta.get("default_target", ""),
            }
            for key, meta in SCAN_OPERATIONS.items()
        },
    }


# ========== URL Analyzer Scan Manager ==========
# Tracks live URL analysis scans and broadcasts progress to the dashboard.

_url_lock = threading.Lock()
_url_active: Optional[Dict[str, Any]] = None
_url_last: Optional[Dict[str, Any]] = None

# ── URL analysis rate limiting ──
# Sliding-window limiter: at most _URL_RATE_MAX scans per _URL_RATE_WINDOW
# seconds. Applied to every entry point (panel button, chat intent, voice
# intent) so the analyzer can't be hammered.
_URL_RATE_MAX = 5
_URL_RATE_WINDOW = 60.0
_url_rate_stamps: list = []
_url_rate_lock = threading.Lock()


def _url_rate_allowed() -> bool:
    """Return True when a new scan may start (enforces a sliding window)."""
    now = time.time()
    with _url_rate_lock:
        _url_rate_stamps[:] = [
            t for t in _url_rate_stamps if now - t < _URL_RATE_WINDOW
        ]
        if len(_url_rate_stamps) >= _URL_RATE_MAX:
            return False
        _url_rate_stamps.append(now)
        return True


def _url_public_state(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Strip non-serializable internals before sending scan state to clients."""
    if not state:
        return None
    return {k: v for k, v in state.items() if not k.startswith("_")}


def _url_set_state(**updates: Any) -> None:
    """Update the active URL scan state and broadcast it to all dashboard clients."""
    snapshot = None
    with _url_lock:
        if _url_active is None:
            return
        _url_active.update(updates)
        snapshot = _url_public_state(_url_active)
    if snapshot:
        broadcast_message_sync({"type": "url_status", "data": snapshot})


def _url_run_worker(scan_id: str, url: str, source: str) -> None:
    """Background worker executing the URL analysis pipeline."""
    global _url_active, _url_last
    try:
        def on_stage(stage_update, full_state):
            _url_set_state(**stage_update)

        def on_complete(result):
            global _url_active, _url_last
            with _url_lock:
                if _url_active is not None and _url_active.get("scan_id") == scan_id:
                    _url_active.update({
                        "status": "COMPLETE",
                        "stage": "complete",
                        "stage_label": "ANALYSIS COMPLETE",
                        "stage_status": "done",
                        "progress": 100,
                        "result": result,
                        "scan_id": result.get("scan_id", scan_id),
                        "chat_response": build_chat_ack(result.get("url")),
                        "voice_summary": build_voice_summary(result),
                        "finished_at": time.time(),
                    })
                    snapshot = _url_public_state(_url_active)
                    _url_last = dict(_url_active)
                    _url_active = None
                else:
                    snapshot = None
            if snapshot:
                broadcast_message_sync({"type": "url_status", "data": snapshot})

        start_scan(url, source=source, on_stage=on_stage, on_complete=on_complete, scan_id=scan_id)

    except Exception as e:
        with _url_lock:
            if _url_active is not None:
                _url_active.update(status="ERROR", stage="error",
                                    error=str(e), progress=100)
                snapshot = _url_public_state(_url_active)
                _url_active = None
            else:
                snapshot = None
        if snapshot:
            broadcast_message_sync({"type": "url_status", "data": snapshot})
        broadcast_message_sync({"type": "url_error", "data": {"reason": str(e)}})


# Maximum wall-clock lifetime of a URL scan. The pipeline's own timeouts
# (DNS/TLS/HTTP) already bound individual network ops, but a hung worker
# thread must never permanently block all future scans, so this watchdog
# forcibly clears _url_active once the deadline is exceeded.
_URL_SCAN_MAX_LIFETIME = 90  # seconds


def _url_watchdog(scan_id: str, deadline: float) -> None:
    """Clear a stuck _url_active once it passes its deadline."""
    global _url_active
    while time.time() < deadline:
        with _url_lock:
            active = _url_active
        if active is None or active.get("scan_id") != scan_id:
            return  # scan finished normally
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(2.0, remaining))
    snapshot = None
    with _url_lock:
        active = _url_active
        if active is not None and active.get("scan_id") == scan_id:
            _url_active.update({
                "status": "ERROR",
                "stage": "error",
                "stage_label": "ANALYSIS TIMED OUT",
                "stage_status": "fail",
                "progress": 100,
                "error": "Unable to reach the destination within the allowed time.",
                "finished_at": time.time(),
            })
            snapshot = _url_public_state(_url_active)
            _url_last = dict(_url_active)
            _url_active = None
    if snapshot:
        broadcast_message_sync({"type": "url_status", "data": snapshot})
        broadcast_message_sync({
            "type": "url_error",
            "data": {"reason": snapshot.get("error", "Scan timed out.")},
        })


def start_url_scan(url: str, source: str = "panel") -> Dict[str, Any]:
    """Validate and launch a background URL analysis scan."""
    global _url_active
    if not url or not url.strip():
        return {"success": False, "error": "Please enter a valid URL."}

    if not _url_rate_allowed():
        return {
            "success": False,
            "error": ("Too many URL analyses in a short time. "
                      "Please wait a moment before starting another scan."),
        }

    now = time.time()
    with _url_lock:
        if _url_active is not None:
            # Recover from a previously hung scan: if it has exceeded its
            # max lifetime, treat it as timed out so the dashboard can move on.
            if now - float(_url_active.get("started_at") or 0) > _URL_SCAN_MAX_LIFETIME:
                _url_active.update({
                    "status": "ERROR", "stage": "error",
                    "stage_label": "ANALYSIS TIMED OUT",
                    "stage_status": "fail", "progress": 100,
                    "error": "Unable to reach the destination within the allowed time.",
                    "finished_at": now,
                })
                stale = _url_public_state(_url_active)
                _url_last = dict(_url_active)
                _url_active = None
                broadcast_message_sync({"type": "url_status", "data": stale})
            else:
                return {"success": False,
                        "error": "A URL scan is already running. Wait for it to complete."}

        # Generate the scan id here and pass it through to the worker,
        # which calls start_scan(scan_id=...) with the callbacks. Do NOT
        # call start_scan() here — that would spawn a second callback-less
        # inner thread and desync the scan registry from _url_active.
        from datetime import datetime as _dt
        import uuid as _uuid
        scan_id = f"url_{_dt.now().strftime('%Y%m%d_%H%M%S')}_{_uuid.uuid4().hex[:6]}"
        from backend.url_analyzer.analyzer import SCAN_STAGES as _URL_STAGES
        state = {"stages": [{"key": k, "label": l, "status": "pending"}
                            for k, l in _URL_STAGES]}
        _url_active = {
            "scan_id": scan_id,
            "url": url.strip(),
            "source": source,
            "status": "RUNNING",
            "stage": "initializing",
            "stage_label": "INITIALIZING URL ANALYZER...",
            "stage_status": "running",
            "progress": 4,
            "stages": state.get("stages", []) if state else [],
            "started_at": time.time(),
            "error": None,
        }
        snapshot = _url_public_state(_url_active)
        deadline = _url_active["started_at"] + _URL_SCAN_MAX_LIFETIME

    broadcast_message_sync({"type": "url_status", "data": snapshot})

    threading.Thread(
        target=_url_run_worker,
        args=(scan_id, url.strip(), source),
        daemon=True,
        name=f"ZYRA-URL-{scan_id}",
    ).start()
    threading.Thread(
        target=_url_watchdog,
        args=(scan_id, deadline),
        daemon=True,
        name=f"ZYRA-URL-WD-{scan_id}",
    ).start()
    return {"success": True, "scan_id": scan_id}


# ========== DNS Lookup Scan Manager ==========
# Tracks live DNS lookups and broadcasts progress to the dashboard, mirroring
# the URL Analyzer scan manager. Lookup state lives in the backend package
# registry; this manager owns the dashboard-facing state + broadcasts.

_dns_lock = threading.Lock()
_dns_active: Optional[Dict[str, Any]] = None
_dns_last: Optional[Dict[str, Any]] = None

# Rate limiting: DNS lookups are lightweight (pure dnspython queries), but
# they must still not be hammerable.
_DNS_RATE_MAX = 10
_DNS_RATE_WINDOW = 60.0
_dns_rate_stamps: list = []
_dns_rate_lock = threading.Lock()

# Longest allowed wall-clock lifetime of one DNS lookup.
_DNS_LOOKUP_MAX_LIFETIME = 60  # seconds


def _dns_rate_allowed() -> bool:
    """Return True when a new lookup may start (sliding window limiter)."""
    now = time.time()
    with _dns_rate_lock:
        _dns_rate_stamps[:] = [
            t for t in _dns_rate_stamps if now - t < _DNS_RATE_WINDOW
        ]
        if len(_dns_rate_stamps) >= _DNS_RATE_MAX:
            return False
        _dns_rate_stamps.append(now)
        return True


def _dns_public_state(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Strip non-serializable internals before sending lookup state to clients."""
    if not state:
        return None
    return {k: v for k, v in state.items() if not k.startswith("_")}


def _dns_set_state(**updates: Any) -> None:
    """Update the active DNS lookup state and broadcast it to all clients."""
    snapshot = None
    with _dns_lock:
        if _dns_active is None:
            return
        _dns_active.update(updates)
        snapshot = _dns_public_state(_dns_active)
    if snapshot:
        broadcast_message_sync({"type": "dns_status", "data": snapshot})


def _dns_finish(scan_id: str, result: Dict[str, Any]) -> None:
    """Move the finished lookup from _dns_active to _dns_last and broadcast."""
    global _dns_active, _dns_last
    error_result = result is not None and not result.get("success")
    with _dns_lock:
        if _dns_active is not None and _dns_active.get("lookup_id") == scan_id:
            _dns_active.update({
                "status": "ERROR" if error_result else "COMPLETE",
                "stage": "complete" if not error_result else "error",
                "stage_label": ("DNS LOOKUP COMPLETE" if not error_result
                                else "DNS LOOKUP FAILED"),
                "stage_status": "done" if not error_result else "fail",
                "progress": 100,
                "result": result,
                "chat_response": dns_build_chat_ack(result.get("domain")),
                "voice_summary": dns_build_voice_summary(result),
                "finished_at": time.time(),
            })
            snapshot = _dns_public_state(_dns_active)
            _dns_last = dict(_dns_active)
            _dns_active = None
        else:
            snapshot = None
    if snapshot:
        try:
            dns_history_add(result)
        except Exception:  # noqa: BLE001 — history is best-effort
            pass
        broadcast_message_sync({"type": "dns_status", "data": snapshot})

def _dns_run_worker(lookup_id: str, domain: str, source: str,
                    record_type: str = None, extra_on_complete=None) -> None:
    """Background worker executing the DNS lookup pipeline."""
    global _dns_active, _dns_last
    try:
        def on_stage(stage_update, full_state):
            _dns_set_state(**stage_update)

        def on_complete(result):
            _dns_finish(lookup_id, result)
            if extra_on_complete:
                try:
                    extra_on_complete(result)
                except Exception:
                    pass

        start_dns_lookup(domain, source=source, on_stage=on_stage,
                         on_complete=on_complete, lookup_id=lookup_id,
                         record_type=record_type)
    except Exception as e:
        with _dns_lock:
            if _dns_active is not None:
                _dns_active.update(status="ERROR", stage="error",
                                   error=str(e), progress=100)
                snapshot = _dns_public_state(_dns_active)
                _dns_last = dict(_dns_active)
                _dns_active = None
            else:
                snapshot = None
        if snapshot:
            broadcast_message_sync({"type": "dns_status", "data": snapshot})
        broadcast_message_sync({"type": "dns_error", "data": {"reason": str(e)}})


def _dns_watchdog(lookup_id: str, deadline: float) -> None:
    """Clear a stuck _dns_active once it passes its deadline."""
    global _dns_active
    while time.time() < deadline:
        with _dns_lock:
            active = _dns_active
        if active is None or active.get("lookup_id") != lookup_id:
            return  # lookup finished normally
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(2.0, remaining))
    snapshot = None
    with _dns_lock:
        active = _dns_active
        if active is not None and active.get("lookup_id") == lookup_id:
            _dns_active.update({
                "status": "ERROR",
                "stage": "error",
                "stage_label": "DNS LOOKUP TIMED OUT",
                "stage_status": "fail",
                "progress": 100,
                "error": "The DNS resolver did not respond within the allowed time.",
                "finished_at": time.time(),
            })
            snapshot = _dns_public_state(_dns_active)
            _dns_last = dict(_dns_active)
            _dns_active = None
    if snapshot:
        broadcast_message_sync({"type": "dns_status", "data": snapshot})
        broadcast_message_sync({
            "type": "dns_error",
            "data": {"reason": snapshot.get("error", "DNS lookup timed out.")},
        })


def start_dns_lookup_job(domain: str, source: str = "panel",
                         record_type: str = None,
                         extra_on_complete=None) -> Dict[str, Any]:
    """
    Validate and launch a background DNS lookup.

    Returns {"success": bool, "lookup_id": ..., "error": ...}.
    """
    global _dns_active
    if not domain or not str(domain).strip():
        return {"success": False, "error": "Please enter a valid domain."}

    if not _dns_rate_allowed():
        return {
            "success": False,
            "error": ("Too many DNS lookups in a short time. "
                      "Please wait a moment before starting another one."),
        }

    now = time.time()
    with _dns_lock:
        if _dns_active is not None:
            # Recover from a previously hung lookup.
            if now - float(_dns_active.get("started_at") or 0) > _DNS_LOOKUP_MAX_LIFETIME:
                _dns_active.update({
                    "status": "ERROR", "stage": "error",
                    "stage_label": "DNS LOOKUP TIMED OUT",
                    "stage_status": "fail", "progress": 100,
                    "error": "The DNS resolver did not respond within the allowed time.",
                    "finished_at": now,
                })
                stale = _dns_public_state(_dns_active)
                _dns_last = dict(_dns_active)
                _dns_active = None
                broadcast_message_sync({"type": "dns_status", "data": stale})
            else:
                return {"success": False,
                        "error": "A DNS lookup is already running. Wait for it to complete."}

        from datetime import datetime as _dt
        import uuid as _uuid
        lookup_id = f"dns_{_dt.now().strftime('%Y%m%d_%H%M%S')}_{_uuid.uuid4().hex[:6]}"
        _dns_active = {
            "lookup_id": lookup_id,
            "domain": str(domain).strip(),
            "source": source,
            "status": "RUNNING",
            "stage": "initializing",
            "stage_label": "INITIALIZING DNS LOOKUP...",
            "stage_status": "running",
            "progress": 5,
            "record_type": (record_type or "ANY").upper(),
            "stages": [{"key": k, "label": l, "status": "pending"}
                       for k, l in DNS_STAGES],
            "started_at": time.time(),
            "error": None,
        }
        snapshot = _dns_public_state(_dns_active)
        deadline = _dns_active["started_at"] + _DNS_LOOKUP_MAX_LIFETIME

    broadcast_message_sync({"type": "dns_status", "data": snapshot})

    threading.Thread(
        target=_dns_run_worker,
        args=(lookup_id, str(domain).strip(), source, record_type, extra_on_complete),
        daemon=True,
        name=f"ZYRA-DNS-{lookup_id}",
    ).start()
    threading.Thread(
        target=_dns_watchdog,
        args=(lookup_id, deadline),
        daemon=True,
        name=f"ZYRA-DNS-WD-{lookup_id}",
    ).start()
    return {"success": True, "lookup_id": lookup_id}


# ========== REST API Endpoints ==========

@app.get("/")
async def get_dashboard():
    """Serve the main dashboard HTML page"""
    index_path = os.path.join(DASHBOARD_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    # Always revalidate the dashboard HTML so UI updates (e.g. the Settings
    # panel) are never shadowed by the browser's heuristic disk cache.
    return FileResponse(index_path, headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "zyra": "running",
        "version": "1.0.0"
    }


@app.post("/api/chat")
async def chat_endpoint(data: Dict[str, Any]):
    """
    Send a chat message to Zyra

    Request body:
    {
        "message": "Hello Zyra, how are you?"
    }

    Response:
    {
        "success": true,
        "response": "I'm doing great! How can I help you today?"
    }
    """
    message = data.get("message", "")
    if not message:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Message is required"}
        )

    try:
        response = process_chat(message)
        return {"success": True, "response": response}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/command")
async def command_endpoint(data: Dict[str, Any]):
    """
    Execute a Zyra command

    Request body:
    {
        "command": "open_chrome",
        "params": {}
    }

    Response:
    {
        "success": true,
        "data": "Executed open_chrome"
    }
    """
    command = data.get("command", "")
    params = data.get("params", {})

    if not command:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Command is required"}
        )

    try:
        result = process_command(command, params)
        return result
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/voice")
async def voice_endpoint(data: Dict[str, Any]):
    """
    Process a voice command (transcribed text)

    Request body:
    {
        "text": "open chrome"
    }

    Response:
    {
        "success": true,
        "data": {
            "response": "Opening Chrome",
            "action": "open_chrome"
        }
    }
    """
    text = data.get("text", "")
    if not text:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Text is required"}
        )

    try:
        result = process_voice_command(text)
        return {"success": True, "data": result}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/speak")
async def speak_endpoint(data: Dict[str, Any]):
    """
    Make Zyra speak text through TTS

    Request body:
    {
        "text": "Hello, I am Zyra"
    }

    Response:
    {
        "success": true,
        "data": "Speaking"
    }
    """
    text = data.get("text", "")
    if not text:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Text is required"}
        )

    try:
        speak_text(text)
        return {"success": True, "data": "Speaking"}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/analyze-link")
async def analyze_link_endpoint(data: Dict[str, Any]):
    """
    Backend-only link security analysis.
    Inspects a URL for phishing, malicious intent, or suspicious attributes.
    Never modifies the frontend dashboard UI — returns a text-only report.

    Request body (provide either field):
        {"url": "http://example.com/login"}
        {"text": "Analyse the link http://example.com/login"}

    Response:
        {"success": true, "report": "...", "analysis": {...}}
    """
    url = (data.get("url") or "").strip()
    text = (data.get("text") or "").strip()
    target = url or (extract_url(text) if text else "")
    if not target:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Provide 'url' or 'text' containing a URL"}
        )
    try:
        analysis = analyze_url_security(target)
        report = format_security_report(analysis)
        return {"success": True, "report": report, "analysis": analysis}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/system/metrics")
@app.get("/api/system-metrics")
async def system_metrics_endpoint():
    """Get real-time system monitoring metrics."""
    try:
        metrics = get_system_metrics()
        return {"success": True, "data": metrics, "formatted": format_system_monitor_text(metrics)}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/system/monitor")
async def system_monitor_trigger_endpoint():
    """Trigger and activate System Monitor."""
    try:
        metrics = get_system_metrics()
        formatted = format_system_monitor_text(metrics)
        await manager.broadcast({
            "type": "show_system_monitor",
            "data": metrics,
            "formatted": formatted,
        })
        return {"success": True, "data": metrics, "formatted": formatted}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/commands")
async def list_commands():
    """List all available Zyra commands"""
    from backend.zyra_bridge import COMMAND_MAP
    commands = list(COMMAND_MAP.keys())
    return {
        "success": True,
        "commands": commands,
        "count": len(commands)
    }


# ========== Nmap Scanner API ==========

@app.get("/api/nmap/state")
async def nmap_state_endpoint():
    """Current Nmap module state: availability, operations, active/last scan."""
    try:
        return {"success": True, "data": get_nmap_state()}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/nmap/operations")
async def nmap_operations_endpoint():
    """List whitelisted Nmap operations available to the dashboard."""
    return {
        "success": True,
        "operations": [
            {"key": key, "label": meta["label"], "description": meta.get("description", ""),
             "default_target": meta.get("default_target", "")}
            for key, meta in SCAN_OPERATIONS.items()
        ],
    }


@app.post("/api/nmap/scan")
async def nmap_scan_endpoint(data: Dict[str, Any]):
    """
    Start a whitelisted Nmap scan (manual or chat/voice triggered).

    Request body:
    {
        "operation": "network_discovery",   // required, whitelisted key
        "target": "192.168.1.0/24",        // required, validated
        "ports": "80,443",                 // optional
        "request_text": "Scan my network"  // optional original user phrasing
    }
    """
    operation = (data.get("operation") or data.get("action") or "").strip()
    target = (data.get("target") or "").strip()
    ports = data.get("ports")
    request_text = (data.get("request_text") or data.get("request") or "").strip()

    if not operation and request_text:
        op_key, _meta = resolve_operation(request_text)
        operation = op_key
    if not target:
        extracted = extract_target(request_text) if request_text else None
        if extracted:
            target = extracted

    if not operation:
        return JSONResponse(status_code=400, content={
            "success": False,
            "error": "Provide a 'operation' (whitelisted scan key) or a 'request_text' describing the scan.",
        })

    result = start_nmap_scan(operation, target, ports=ports, request_text=request_text)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)

    with _nmap_lock:
        state = _nmap_public_state(_nmap_active) or {}
    return {"success": True, "data": state}


@app.get("/api/nmap/result/{scan_id}")
async def nmap_result_endpoint(scan_id: str):
    """Fetch a stored scan result by id."""
    result = get_result(scan_id)
    if not result:
        return JSONResponse(status_code=404,
                            content={"success": False, "error": f"Scan result '{scan_id}' not found or expired."})
    pub = {k: v for k, v in result.items() if not k.startswith("_")}
    return {"success": True, "data": pub}


@app.get("/api/nmap/report/{scan_id}")
async def nmap_report_endpoint(scan_id: str, format: str = "json"):
    """
    Generate and download a scan report.

    format=json  -> structured machine-readable JSON
    format=pdf   -> human-readable PDF cybersecurity report
    format=txt   -> plain-text report
    """
    result = get_result(scan_id)
    if not result:
        return JSONResponse(status_code=404,
                            content={"success": False, "error": f"Scan result '{scan_id}' not found or expired. Run a scan first."})
    fmt = (format or "json").lower()
    try:
        report = build_report_data(result)
        if fmt in ("json",):
            content = report_to_json(report)
            return Response(
                content=content,
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="zyra_nmap_report_{scan_id}.json"'},
            )
        if fmt in ("pdf",):
            pdf_bytes = report_to_pdf(report)
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="zyra_nmap_report_{scan_id}.pdf"'},
            )
        if fmt in ("txt", "text"):
            return Response(
                content=report_to_text(report),
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="zyra_nmap_report_{scan_id}.txt"'},
            )
        return JSONResponse(status_code=400,
                            content={"success": False, "error": f"Unsupported format '{format}'. Use json, pdf or txt."})
    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"success": False, "error": f"Report generation failed: {e}"})


# ========== URL Analyzer API ==========


@app.post("/api/url/analyze")
async def url_analyze_endpoint(data: Dict[str, Any]):
    """
    Start a URL security analysis scan.

    Request body:
    {
        "url": "https://example.com",
        "source": "panel" | "chat" | "voice"   // optional, default "panel"
    }

    Response:
    {"success": true, "scan_id": "url_..."}
    """
    url = (data.get("url") or "").strip()
    source = (data.get("source") or "panel").strip()
    if not url:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Provide a 'url' to analyze."}
        )
    result = start_url_scan(url, source=source)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return {"success": True, "scan_id": result["scan_id"]}


@app.get("/api/url/status/{scan_id}")
async def url_status_endpoint(scan_id: str):
    """Current live status of a URL scan (for polling fallback)."""
    state = get_scan_state(scan_id)
    if not state:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Scan '{scan_id}' not found."}
        )
    return {"success": True, "data": state}


@app.get("/api/url/result/{scan_id}")
async def url_result_endpoint(scan_id: str):
    """Fetch a completed scan's full result payload."""
    state = get_scan_state(scan_id)
    if not state:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Scan '{scan_id}' not found."}
        )
    result = state.get("result")
    if not result:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Scan has not completed yet."}
        )
    return {"success": True, "data": result}


@app.get("/api/url/report/{scan_id}")
async def url_report_endpoint(scan_id: str, format: str = "json"):
    """
    Generate a URL analysis report.

    format=json  -> structured result payload
    format=txt   -> plain-text report
    format=pdf   -> downloadable PDF report
    """
    state = get_scan_state(scan_id)
    if not state:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Scan '{scan_id}' not found. Run a scan first."}
        )
    result = state.get("result")
    if not result:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Scan has not completed yet."}
        )
    fmt = (format or "json").lower()
    try:
        report = url_build_report_data(result)
        if fmt == "json":
            return {"success": True, "data": report}
        if fmt in ("txt", "text"):
            return Response(
                content=url_report_to_text(report),
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{report_filename(result)}.txt"'},
            )
        if fmt == "pdf":
            pdf_bytes = url_report_to_pdf(report)
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{report_filename(result)}.pdf"'},
            )
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"Unsupported format '{format}'. Use json, pdf or txt."}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Report generation failed: {e}"}
        )


@app.get("/api/url/history")
async def url_history_endpoint():
    """Recent URL scan history for the panel."""
    return {"success": True, "data": get_history(8)}


# ========== DNS Lookup Endpoints ==========

@app.post("/api/dns/lookup")
async def dns_lookup_endpoint(data: Dict[str, Any]):
    """
    Run a real DNS lookup for a domain (or reverse lookup for an IP).

    Request body:
        {"domain": "example.com"}          # panel / programmatic
        {"text": "Analyze DNS of example.com"}  # raw chat-style input
        {"source": "panel"}                # optional: panel | chat | voice

    The lookup runs in a background thread (live progress is streamed to
    dashboard clients over WebSocket as `dns_status` messages). The endpoint
    waits for completion (up to ~50s — typical lookups take 1-5s) and returns
    the full structured result: DNS records (A, AAAA, CNAME, MX, NS, TXT,
    SOA, PTR), DNSSEC status, TTLs, response time, resolution status and
    errors (NXDOMAIN / SERVFAIL / timeout).
    """
    domain = (data.get("domain") or data.get("target") or "").strip()
    text = (data.get("text") or "").strip()
    source = (data.get("source") or "panel").strip().lower() or "panel"
    record_type = (data.get("record_type") or data.get("query_type") or "ANY").strip().upper()

    if not domain and text:
        # Accept raw chat-style input; extract the domain from it.
        extracted = extract_dns_target(text)
        if extracted:
            domain = extracted
        elif not is_dns_intent(text):
            domain = text  # let the validator produce a helpful error
    if not domain:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Domain is required"},
        )

    holder: Dict[str, Any] = {"result": None}
    done = threading.Event()

    def _on_done(result):
        holder["result"] = result
        done.set()

    launch = start_dns_lookup_job(domain, source=source,
                                  record_type=record_type,
                                  extra_on_complete=_on_done)
    if not launch.get("success"):
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": launch.get("error", "Lookup could not be started.")},
        )

    lookup_id = launch.get("lookup_id")
    done.wait(timeout=50)

    result = holder.get("result")
    if result is None:
        # Timed out waiting — check the registry once more before giving up.
        state = get_dns_scan_state(lookup_id)
        if state and state.get("result"):
            result = state["result"]
    if result is not None and result.get("success"):
        return {"success": True, "lookup_id": lookup_id, "result": result}
    if result is not None:
        # Validation / lookup error surfaced gracefully (never a crash).
        return JSONResponse(
            status_code=400,
            content={"success": False, "lookup_id": lookup_id,
                     "error": result.get("error", "DNS lookup failed.")},
        )

    # Still running after 50s (rare): report pending state.
    return JSONResponse(
        status_code=202,
        content={"success": True, "lookup_id": lookup_id, "pending": True,
                 "message": "DNS lookup still running; poll /api/dns/result/<id>."},
    )


@app.get("/api/dns/result/{lookup_id}")
async def dns_result_endpoint(lookup_id: str):
    """Full stored result for a completed DNS lookup (panel reopen)."""
    state = get_dns_scan_state(lookup_id)
    if not state:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Lookup '{lookup_id}' not found."}
        )
    return {"success": True, "data": state}


@app.get("/api/dns/report/{lookup_id}")
async def dns_report_endpoint(lookup_id: str, format: str = "json"):
    """
    Generate a DNS lookup report.

    format=json  -> structured result payload
    format=txt   -> plain-text report
    format=pdf   -> downloadable PDF report
    """
    state = get_dns_scan_state(lookup_id)
    result = None
    if state:
        result = state.get("result")
    if not result:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Lookup '{lookup_id}' not found. Run a lookup first."}
        )
    fmt = (format or "json").lower()
    try:
        report = dns_build_report_data(result)
        if fmt == "json":
            return {"success": True, "data": report}
        if fmt in ("txt", "text"):
            return Response(
                content=dns_report_to_text(report),
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{dns_report_filename(result)}.txt"'},
            )
        if fmt == "pdf":
            pdf_bytes = dns_report_to_pdf(report)
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{dns_report_filename(result)}.pdf"'},
            )
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"Unsupported format '{format}'. Use json, pdf or txt."}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Report generation failed: {e}"}
        )


@app.get("/api/dns/history")
async def dns_history_endpoint():
    """Recent DNS lookup history for the panel."""
    return {"success": True, "data": dns_history_recent(8)}


@app.post("/api/dns/report")
async def dns_report_generate_endpoint(data: Dict[str, Any]):
    """
    Generate a DNS lookup report from a result payload the dashboard already
    holds (panel 'GENERATE REPORT' button).

    Request body:
        {"domain": "example.com", "result": { ...completed lookup result... }}

    With format=json (default) returns the assembled report structure.
    With format=txt or format=pdf returns the generated report as a
    downloadable attachment — so 'DOWNLOAD REPORT' always fetches the real
    server-generated report, even for lookups no longer in the registry.
    """
    result = data.get("result") or {}
    if not result:
        return JSONResponse(
            status_code=400,
            content={"success": False,
                     "error": "No DNS lookup result provided."},
        )
    fmt = (data.get("format") or "json").strip().lower()
    try:
        report = dns_build_report_data(result)
        if fmt in ("txt", "text"):
            return Response(
                content=dns_report_to_text(report),
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{dns_report_filename(result)}.txt"'},
            )
        if fmt == "pdf":
            pdf_bytes = dns_report_to_pdf(report)
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{dns_report_filename(result)}.pdf"'},
            )
        return {
            "success": True,
            "report_id": f"dns_{result.get('lookup_id', 'manual')}",
            "data": report,
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Report generation failed: {e}"}
        )


# ========== WebSocket Endpoint ==========

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time communication with Zyra

    Message format (JSON):
    {
        "type": "chat|command|voice|speak|remember|recall",
        "data": "..."
    }

    Response format:
    {
        "type": "response",
        "success": true,
        "data": "..."
    }
    """
    await manager.connect(websocket)
    try:
        while True:
            # Receive message from client
            raw_data = await websocket.receive_text()

            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                await manager.send_personal(
                    {"type": "error", "success": False, "error": "Invalid JSON"},
                    websocket
                )
                continue

            msg_type = data.get("type", "")
            msg_data = data.get("data")

            # Process the message through Zyra bridge
            try:
                result = process_message(msg_type, msg_data)

                # Metrics-type requests answer with their own message type so the
                # dashboard updates the live monitor card instead of the chat feed.
                is_metrics_request = msg_type in (
                    "system_metrics",
                    "get_system_metrics",
                    "monitor_system",
                    "start_monitoring",
                )

                # Send response back to the client
                response = {
                    "type": "system_metrics" if is_metrics_request else "response",
                    "success": result.get("success", False),
                    "data": result.get("data", result.get("response")),
                }
                if "error" in result:
                    response["error"] = result["error"]

                await manager.send_personal(response, websocket)

                # If it's a system monitor intent or action, broadcast card trigger
                # (covers both voice commands and chat messages like "Monitor my system")
                chat_monitor_intent = (
                    msg_type == "chat"
                    and isinstance(msg_data, str)
                    and is_system_monitor_intent(msg_data)
                )
                if result.get("action") == "system_monitor" or chat_monitor_intent:
                    metrics = result.get("metrics") or get_system_metrics()
                    await manager.broadcast({
                        "type": "show_system_monitor",
                        "data": metrics,
                        "formatted": format_system_monitor_text(metrics),
                    })

                # If it's a voice command with a response, also broadcast to all
                if msg_type == "voice" and result.get("success"):
                    voice_data = result.get("data", {})
                    if isinstance(voice_data, dict) and voice_data.get("response"):
                        await manager.broadcast({
                            "type": "voice_response",
                            "data": voice_data["response"]
                        })

                # ── Nmap intent from chat or voice ──
                # Launch the whitelisted scan in a background thread and
                # auto-open the Nmap Scanner panel on the dashboard.
                nmap_text = ""
                if isinstance(msg_data, str):
                    nmap_text = msg_data
                elif isinstance(msg_data, dict):
                    nmap_text = msg_data.get("text") or msg_data.get("message") or ""
                nmap_intent = (
                    msg_type in ("chat", "voice")
                    and bool(nmap_text)
                    and (result.get("action") == "nmap_scan" or is_nmap_intent(nmap_text))
                )
                if nmap_intent:
                    op_key, op_meta = resolve_operation(nmap_text)
                    n_target = extract_target(nmap_text) or op_meta.get("default_target", "127.0.0.1")
                    launch = start_nmap_scan(op_key, n_target, request_text=nmap_text)
                    if launch.get("success"):
                        with _nmap_lock:
                            state = _nmap_public_state(_nmap_active) or {}
                        await manager.broadcast({
                            "type": "show_nmap_scanner",
                            "data": state,
                        })
                    else:
                        await manager.send_personal(
                            {
                                "type": "nmap_error",
                                "data": {"reason": launch.get("error", "Scan could not be started.")},
                            },
                            websocket,
                        )

                # ── DNS lookup intent from chat or voice ──
                # Detect the intent, extract the domain, open the DNS Lookup
                # panel and run the real lookup. The panel streams live
                # progress from the background worker.
                dns_text = ""
                if isinstance(msg_data, str):
                    dns_text = msg_data
                elif isinstance(msg_data, dict):
                    dns_text = msg_data.get("text") or msg_data.get("message") or ""
                dns_intent = (
                    msg_type in ("chat", "voice")
                    and bool(dns_text)
                    and is_dns_intent(dns_text)
                )
                if dns_intent:
                    dns_target = extract_dns_target(dns_text)
                    if dns_target:
                        dns_source = "voice" if msg_type == "voice" else "chat"
                        dns_rtype = extract_dns_record_type(dns_text)
                        dns_launch = start_dns_lookup_job(
                            dns_target, source=dns_source, record_type=dns_rtype)
                        if dns_launch.get("success"):
                            with _dns_lock:
                                dns_state = _dns_public_state(_dns_active) or {}
                            await manager.broadcast({
                                "type": "show_dns_lookup",
                                "data": dns_state,
                                "domain": dns_target,
                            })
                        else:
                            await manager.send_personal(
                                {
                                    "type": "dns_error",
                                    "data": {"reason": dns_launch.get("error", "DNS lookup could not be started.")},
                                },
                                websocket,
                            )
                    else:
                        await manager.send_personal(
                            {
                                "type": "response",
                                "success": True,
                                "data": "I detected a DNS lookup request, but could not extract a valid domain. Please provide one like: \"Analyze DNS of example.com\".",
                            },
                            websocket,
                        )

                # ── URL analysis intent from chat or voice ──
                # Detect the intent, extract the URL, open the URL Analyzer panel
                # and start the scan. The panel streams live progress from the
                # background worker.
                url_text = ""
                if isinstance(msg_data, str):
                    url_text = msg_data
                elif isinstance(msg_data, dict):
                    url_text = msg_data.get("text") or msg_data.get("message") or ""
                url_intent = (
                    msg_type in ("chat", "voice")
                    and bool(url_text)
                    and is_url_analysis_intent(url_text)
                )
                if url_intent:
                    target_url = extract_target_url(url_text)
                    if target_url:
                        source = "voice" if msg_type == "voice" else "chat"
                        launch = start_url_scan(target_url, source=source)
                        if launch.get("success"):
                            with _url_lock:
                                state = _url_public_state(_url_active) or {}
                            await manager.broadcast({
                                "type": "show_url_analyzer",
                                "data": state,
                                "url": target_url,
                            })
                        else:
                            await manager.send_personal(
                                {
                                    "type": "url_error",
                                    "data": {"reason": launch.get("error", "URL analysis could not be started.")},
                                },
                                websocket,
                            )
                    else:
                        await manager.send_personal(
                            {
                                "type": "response",
                                "success": True,
                                "data": "I detected a URL analysis request, but could not extract a valid URL. Please provide a full URL like https://example.com.",
                            },
                            websocket,
                        )

            except Exception as e:
                await manager.send_personal(
                    {"type": "error", "success": False, "error": str(e)},
                    websocket
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)


# ========== Server Runner ==========

def run_server(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = False):
    """
    Run the FastAPI server

    Args:
        host: Host address to bind to
        port: Port to listen on
        open_browser: Whether to open the dashboard in browser
    """
    if open_browser:
        url = f"http://{host}:{port}"
        print(f"\n🌐 Opening dashboard at {url}")
        webbrowser.open(url)

    print(f"\n🚀 ZYRA Backend Server running at http://{host}:{port}")
    print(f"📡 WebSocket endpoint: ws://{host}:{port}/ws")
    print(f"📋 API docs: http://{host}:{port}/docs")
    print(f"🔍 Health check: http://{host}:{port}/api/health\n")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


def start_server_thread(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = False):
    """
    Start the FastAPI server in a background thread.
    Used when running from main.py alongside the voice assistant.
    """
    server_thread = threading.Thread(
        target=run_server,
        args=(host, port, open_browser),
        daemon=True,
        name="ZYRA-Server"
    )
    server_thread.start()
    return server_thread


if __name__ == "__main__":
    # When run directly, start server and open browser
    run_server(open_browser=True)
