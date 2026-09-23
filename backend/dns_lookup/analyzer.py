"""
backend/dns_lookup/analyzer.py — DNS lookup pipeline orchestrator

Runs the full backend DNS analysis pipeline and produces the structured
result consumed by the dashboard panel, the chat integration, the voice
summary and the report generator:

    INITIALIZING → VALIDATING DOMAIN → RESOLVING DOMAIN →
    QUERYING DNS RECORDS → CHECKING MAIL POLICY → REVERSE DNS →
    ANALYZING DNSSEC → COMPLETE

Every stage emits a live callback so the server can stream real-time
progress to the dashboard over WebSocket. All analysis happens in the
backend — the frontend never fakes a DNS result.
"""

import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime

from backend.dns_lookup.resolver import resolve_all
from backend.dns_lookup.validator import DomainValidationError, validate_domain

# Ordered pipeline stages exposed to the UI
DNS_STAGES = [
    ("initializing", "INITIALIZING DNS LOOKUP..."),
    ("validating", "VALIDATING DOMAIN..."),
    ("resolving", "RESOLVING DOMAIN..."),
    ("records", "QUERYING DNS RECORDS..."),
    ("mail", "CHECKING MAIL POLICY (MX / SPF / DMARC)..."),
    ("reverse", "PERFORMING REVERSE DNS (PTR)..."),
    ("dnssec", "ANALYZING DNSSEC..."),
    ("complete", "DNS LOOKUP COMPLETE"),
]

STAGE_PROGRESS = {
    "initializing": 5,
    "validating": 14,
    "resolving": 28,
    "records": 50,
    "mail": 64,
    "reverse": 78,
    "dnssec": 92,
    "complete": 100,
}

# ──────────────────────────────────────────────
# Lookup registry (thread-safe, in-memory)
# ──────────────────────────────────────────────

_LOCK = threading.Lock()
_LOOKUPS = OrderedDict()        # lookup_id -> state dict (ordered = newest last)
_MAX_LOOKUPS = 25


def _register(state: dict) -> None:
    with _LOCK:
        _LOOKUPS[state["lookup_id"]] = state
        while len(_LOOKUPS) > _MAX_LOOKUPS:
            _LOOKUPS.popitem(last=False)


def get_dns_lookup(lookup_id: str):
    """Full state/result for a lookup_id (in-memory), or None."""
    if not lookup_id:
        return None
    with _LOCK:
        return _LOOKUPS.get(lookup_id)


def get_scan_state(lookup_id: str):
    """Serializable public state for polling/result endpoints."""
    state = get_dns_lookup(lookup_id)
    if not state:
        return None
    return {k: v for k, v in state.items() if not k.startswith("_")}


def get_last_dns_lookup():
    """Most recent lookup id, or None."""
    with _LOCK:
        if _LOOKUPS:
            return next(reversed(_LOOKUPS))
    return None


def _stage_update(stage_key: str, status: str = "running",
                  detail: str = None) -> dict:
    """Build the broadcast payload for a stage transition."""
    label = dict(DNS_STAGES).get(stage_key, stage_key.upper())
    return {
        "stage": stage_key,
        "stage_label": label,
        "stage_status": status,
        "stage_detail": detail,
        "progress": STAGE_PROGRESS.get(stage_key, 0),
    }


# ──────────────────────────────────────────────
# Launcher (background thread)
# ──────────────────────────────────────────────

def start_dns_lookup(domain: str, source: str = "panel", on_stage=None,
                     on_complete=None, lookup_id: str = None,
                     record_type: str = None) -> dict:
    """
    Create a lookup record and run the pipeline in a background thread.

    Returns {"success": bool, "lookup_id": ..., "error": ...} — safe to
    call from async FastAPI handlers.
    """
    if lookup_id is None:
        lookup_id = f"dns_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    state = {
        "lookup_id": lookup_id,
        "domain": (domain or "").strip(),
        "source": source,
        "status": "RUNNING",
        "stage": "initializing",
        "stage_label": dict(DNS_STAGES)["initializing"],
        "stage_status": "running",
        "progress": STAGE_PROGRESS["initializing"],
        "stages": [{"key": k, "label": l, "status": "pending"} for k, l in DNS_STAGES],
        "started_at": time.time(),
        "error": None,
    }
    _register(state)

    threading.Thread(
        target=run_dns_lookup,
        args=(domain,),
        kwargs={
            "lookup_id": lookup_id,
            "source": source,
            "on_stage": on_stage,
            "on_complete": on_complete,
            "record_type": record_type,
        },
        daemon=True,
        name=f"ZYRA-DNS-{lookup_id}",
    ).start()
    return {"success": True, "lookup_id": lookup_id}


# ──────────────────────────────────────────────
# The pipeline
# ──────────────────────────────────────────────

def run_dns_lookup(domain: str, lookup_id: str = None, source: str = "panel",
                   on_stage=None, on_complete=None,
                   record_type: str = None) -> dict:
    """
    Execute the complete DNS lookup pipeline.

    Args:
        domain      — raw user-supplied domain (untrusted)
        lookup_id   — existing lookup id (from start_dns_lookup) or None
        source      — 'panel' | 'chat' | 'voice'
        on_stage    — callable(stage_update_dict, full_state_dict)
        on_complete — callable(final_result_dict)
        record_type — nslookup-style record-type filter ('A', 'MX', 'PTR', ...)
                      or None / 'ANY' for the full lookup of every type

    Returns the final result payload.
    """
    if lookup_id is None:
        lookup_id = f"dns_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    def state_of():
        return get_dns_lookup(lookup_id) or {}

    def emit(stage_key: str, status: str = "running", detail: str = None):
        upd = _stage_update(stage_key, status, detail)
        state = state_of()
        if state:
            state.update(upd)
            seen = False
            for s in state.get("stages", []):
                if s["key"] == stage_key:
                    s["status"] = status
                    seen = True
                elif not seen and s["status"] == "running":
                    s["status"] = "done"
        if on_stage:
            try:
                on_stage(dict(upd), {k: v for k, v in state_of().items()
                                     if not k.startswith("_")})
            except Exception:
                pass

    emit("initializing", "running")

    timestamp = datetime.now().isoformat(timespec="seconds")

    # ── Stage: VALIDATING DOMAIN (sanitize / SSRF guard) ──
    emit("validating", "running")
    try:
        parts = validate_domain(domain)
    except DomainValidationError as e:
        return _fail(state_of, emit, lookup_id, source, timestamp, str(e))

    target = parts["domain"]
    is_ip = parts.get("is_ip", False)

    # Registered-domain apex (reuse the URL analyzer's splitter — same
    # multi-part-suffix logic, no duplicated tables)
    apex = target
    if not is_ip:
        try:
            from backend.url_analyzer.dns_analyzer import split_domain
            apex = split_domain(target).get("registered_domain") or target
        except Exception:
            apex = target

    state = state_of()
    if state:
        state.update({
            "domain": target,
            "domain_display": parts.get("domain_display", target),
            "is_ip": is_ip,
            "apex": apex,
            "record_type": (record_type or "ANY").upper(),
        })

    # ── Stage: QUERY EVERYTHING (resolver runs the real queries) ──
    emit("resolving", "running")

    def _stream_mid_stages():
        # Streams the middle pipeline stages while resolve_all works so the
        # dashboard shows genuine forward progress during the query burst.
        time.sleep(0.05)
        for key in ("records", "mail", "reverse", "dnssec"):
            emit(key, "running")

    threading.Thread(target=_stream_mid_stages, daemon=True).start()

    try:
        analysis = resolve_all(target, is_ip=is_ip, apex=apex)
    except Exception as e:  # noqa: BLE001 — resolver must never crash the pipeline
        return _fail(state_of, emit, lookup_id, source, timestamp,
                     f"DNS resolution failed: {type(e).__name__}")

    for key in ("resolving", "records", "mail", "reverse", "dnssec"):
        emit(key, "done")

    # ── nslookup-style record-type filter ──
    # When a specific type was requested, keep only that block (plus PTR
    # context for A/AAAA lookups). 'ANY' or None keeps every record type.
    requested_type = (record_type or "ANY").upper().strip()
    if requested_type not in ("ANY", "", "ALL"):
        filtered = {}
        if requested_type in analysis.get("records", {}):
            filtered[requested_type] = analysis["records"][requested_type]
        elif requested_type == "PTR":
            ptr = analysis.get("records", {}).get("PTR")
            if ptr:
                filtered["PTR"] = ptr
        analysis["records"] = filtered

    emit("complete", "done")

    status = "RESOLVED" if analysis["resolution"]["resolved"] else "NOT_RESOLVED"

    result = {
        "success": True,
        "lookup_id": lookup_id,
        "source": source,
        "domain": target,
        "domain_display": parts.get("domain_display", target),
        "is_ip": is_ip,
        "apex": apex,
        "record_type": (record_type or "ANY").upper(),
        "dns_server": analysis.get("dns_server", {}),
        "status": status,
        "resolution": analysis.get("resolution", {}),
        "records": analysis.get("records", {}),
        "txt_policy": analysis.get("txt_policy", {}),
        "dnssec": analysis.get("dnssec", {}),
        "reverse": analysis.get("reverse", {}),
        "wildcard": analysis.get("wildcard"),
        "response_time_ms": analysis.get("response_time_ms"),
        "total_time_ms": analysis.get("total_time_ms"),
        "timestamp": timestamp,
        "timestamp_display": datetime.now().strftime("%d %b %Y %H:%M"),
    }

    state = state_of()
    if state:
        state.update({
            "status": "COMPLETE",
            "progress": 100,
            "result": result,
            "finished_at": time.time(),
        })
    if on_complete:
        try:
            on_complete(result)
        except Exception:
            pass
    return result


def _fail(state_of, emit, lookup_id, source, timestamp, error: str) -> dict:
    """Mark the lookup failed and return an error result (never raises)."""
    emit("validating", "fail", error)
    state = state_of()
    if state:
        state.update({
            "status": "ERROR",
            "error": error,
            "progress": 100,
            "finished_at": time.time(),
        })
    result = {
        "success": False,
        "lookup_id": lookup_id,
        "source": source,
        "domain": (state or {}).get("domain", ""),
        "error": error,
        "timestamp": timestamp,
        "timestamp_display": datetime.now().strftime("%d %b %Y %H:%M"),
    }
    if state is not None:
        state["result"] = result
    return result


# ──────────────────────────────────────────────
# Voice summary
# ──────────────────────────────────────────────

def build_voice_summary(result: dict) -> str:
    """
    Voice-friendly spoken response after a DNS lookup, e.g.:

      "The DNS lookup is complete. example.com resolved in 24 milliseconds.
       DNSSEC is enabled."
    """
    if not result:
        return "The DNS lookup could not be completed."
    if not result.get("success"):
        return f"The DNS lookup failed. {result.get('error') or 'Please try again.'}"

    domain = result.get("domain_display") or "the domain"
    ms = result.get("response_time_ms")

    if not result.get("resolution", {}).get("resolved"):
        return (f"The DNS lookup is complete. {domain} could not be resolved. "
                f"It may be unregistered or misconfigured.")

    parts = [f"The DNS lookup is complete. {domain} resolved successfully"]
    if ms is not None:
        parts.append(f"in {int(ms) if ms >= 10 else round(ms, 1)} milliseconds")
    return " ".join(parts)
