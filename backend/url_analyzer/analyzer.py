"""
backend/url_analyzer/analyzer.py â€” URL scan pipeline orchestrator

Runs the full backend analysis pipeline and produces the structured result
consumed by the dashboard panel, the chat integration, the voice summary
and the report generator:

    INITIALIZING â†’ VALIDATING URL â†’ RESOLVING DOMAIN â†’ CHECKING DNS â†’
    ANALYZING SSL/TLS â†’ ANALYZING REDIRECTS â†’ CHECKING DOMAIN INFORMATION â†’
    CHECKING REPUTATION â†’ CHECKING THREAT INDICATORS â†’ ANALYZING URL
    STRUCTURE â†’ CALCULATING RISK SCORE â†’ ANALYSIS COMPLETE

Every stage emits a live callback so the server can stream real-time
progress to the dashboard over WebSocket. All analysis happens in the
backend â€” the frontend never fakes a security result.
"""

import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from urllib.parse import urlparse

from backend.url_analyzer import history
from backend.url_analyzer.dns_analyzer import analyze_dns, split_domain
from backend.url_analyzer.reputation import check_reputation
from backend.url_analyzer.risk_scorer import build_recommendation, score_scan
from backend.url_analyzer.ssl_analyzer import analyze_ssl
from backend.url_analyzer.threat_detector import detect_threats
from backend.url_analyzer.validator import (
    MAX_REDIRECTS,
    REQUEST_TIMEOUT,
    check_redirect_target,
    is_blocked_ip,
    resolve_host_ips,
    validate_url,
)

try:
    from backend.ml_phishing import analyze_url_ml
except Exception:  # ML layer optional — heuristic engine keeps working
    analyze_url_ml = None

# Ordered scan stages exposed to the UI
SCAN_STAGES = [
    ("initializing", "INITIALIZING URL ANALYZER..."),
    ("validating", "VALIDATING URL..."),
    ("resolving", "RESOLVING DOMAIN..."),
    ("dns", "CHECKING DNS..."),
    ("ssl", "ANALYZING SSL/TLS..."),
    ("redirects", "ANALYZING REDIRECTS..."),
    ("domain_info", "CHECKING DOMAIN INFORMATION..."),
    ("reputation", "CHECKING REPUTATION..."),
    ("threats", "CHECKING THREAT INDICATORS..."),
    ("structure", "ANALYZING URL STRUCTURE..."),
    ("scoring", "CALCULATING RISK SCORE..."),
    ("complete", "ANALYSIS COMPLETE"),
]

STAGE_PROGRESS = {
    "initializing": 4,
    "validating": 12,
    "resolving": 22,
    "dns": 32,
    "ssl": 44,
    "redirects": 52,
    "domain_info": 60,
    "reputation": 70,
    "threats": 78,
    "structure": 86,
    "scoring": 94,
    "complete": 100,
}

_REDIRECT_UA = "ZYRA-URL-Analyzer/1.0 (+safety probe; no content execution)"

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Scan registry (thread-safe, in-memory)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_LOCK = threading.Lock()
_SCANS = OrderedDict()          # scan_id -> state dict (ordered = newest last)
_MAX_SCANS = 25


def _register(state: dict) -> None:
    with _LOCK:
        _SCANS[state["scan_id"]] = state
        while len(_SCANS) > _MAX_SCANS:
            _SCANS.popitem(last=False)


def get_scan(scan_id: str):
    """Full state/result for a scan_id (in-memory), or None."""
    if not scan_id:
        return None
    with _LOCK:
        return _SCANS.get(scan_id)


def get_scan_state(scan_id: str):
    """Serializable public state for polling endpoints."""
    state = get_scan(scan_id)
    if not state:
        return None
    return {k: v for k, v in state.items() if not k.startswith("_")}


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Scan launcher (background thread)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def start_scan(url: str, source: str = "panel", on_stage=None,
               on_complete=None, scan_id: str = None) -> dict:
    """
    Create a scan record and run the analysis in a background thread.

    Returns {"success": bool, "scan_id": ..., "error": ...} â€” safe to call
    from async FastAPI handlers.
    """
    if scan_id is None:
        scan_id = f"url_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    state = {
        "scan_id": scan_id,
        "url": (url or "").strip(),
        "source": source,
        "status": "RUNNING",
        "stage": "initializing",
        "stage_label": dict(SCAN_STAGES)["initializing"],
        "stage_status": "running",
        "progress": STAGE_PROGRESS["initializing"],
        "stages": [{"key": k, "label": l, "status": "pending"} for k, l in SCAN_STAGES],
        "started_at": time.time(),
        "error": None,
    }
    _register(state)

    threading.Thread(
        target=run_url_scan,
        args=(url,),
        kwargs={
            "scan_id": scan_id,
            "source": source,
            "on_stage": on_stage,
            "on_complete": on_complete,
        },
        daemon=True,
        name=f"ZYRA-URL-{scan_id}",
    ).start()
    return {"success": True, "scan_id": scan_id}


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Redirect probe (SSRF-guarded, no content execution)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _run_with_timeout(func, args=(), kwargs=None, timeout=20):
    """Run func in a worker thread; return its result or None on timeout."""
    import threading
    kwargs = kwargs or {}
    box = {}
    def _worker():
        try:
            box["result"] = func(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            box["error"] = e
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, "timeout"
    if "error" in box:
        return None, box["error"]
    return box.get("result"), None


def _probe_redirects(url: str, parts: dict, domain_info: dict) -> dict:
    """Follow redirects manually (max 5) with re-validation of each hop."""
    try:
        import requests
    except ImportError:
        return {"chain": [], "note": "HTTP client unavailable â€” redirects not probed."}

    chain = []
    current_url = url
    depth = 0
    headers = {"User-Agent": _REDIRECT_UA, "Accept": "*/*"}

    try:
        while depth < MAX_REDIRECTS:
            ok, ips = resolve_host_ips(
                (urlparse(current_url).hostname or ""), timeout=4
            )
            if ok:
                for ip in ips:
                    if is_blocked_ip(ip):
                        return {
                            "chain": chain, "blocked": True,
                            "block_reason": "Redirect target resolves to a private/internal address.",
                        }
            resp = requests.head(
                current_url, headers=headers, timeout=REQUEST_TIMEOUT,
                allow_redirects=False, stream=True,
            )
            if resp.status_code >= 400:
                # HEAD may be disallowed â€” retry with a closed-body GET.
                resp = requests.get(
                    current_url, headers=headers, timeout=REQUEST_TIMEOUT,
                    allow_redirects=False, stream=True,
                )
                with resp.close():
                    pass

            if resp.is_redirect or resp.is_permanent_redirect or 300 <= resp.status_code < 400:
                location = resp.headers.get("Location", "")
                guard = check_redirect_target(location, depth)
                if not guard["allowed"]:
                    return {"chain": chain, "blocked": True,
                            "block_reason": guard["reason"]}
                from urllib.parse import urljoin
                next_url = urljoin(current_url, location)
                chain.append({"status": resp.status_code,
                              "from": current_url, "to": next_url})
                current_url = next_url
                depth += 1
                continue

            resp.close()
            final_parts = validate_url(current_url)
            final_domain = None
            if final_parts.get("valid") and domain_info:
                final_domain = split_domain(final_parts["hostname"])["registered_domain"]
            return {
                "chain": chain,
                "final_url": current_url,
                "final_registered_domain": final_domain,
                "original_registered_domain": domain_info.get("registered_domain"),
                "blocked": False,
            }
        return {"chain": chain, "blocked": False,
                "block_reason": "Maximum redirect depth exceeded."}
    except Exception as e:
        return {"chain": chain, "note": f"Redirect probe failed ({type(e).__name__})."}


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# The pipeline
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_url_scan(url: str, scan_id: str = None, source: str = "panel",
                 on_stage=None, on_complete=None) -> dict:
    """
    Execute the complete URL analysis pipeline.

    Args:
        url         â€” raw user-supplied URL (untrusted)
        scan_id     â€” existing scan id (from start_scan) or None
        source      â€” 'panel' | 'chat' | 'voice'
        on_stage    â€” callable(stage_update_dict, full_state_dict)
        on_complete â€” callable(final_result_dict)

    Returns the final result payload.
    """
    if scan_id is None:
        scan_id = f"url_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    def state_of():
        return get_scan(scan_id) or {}

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

    # â”€â”€ Stage: VALIDATING URL (SSRF-hardened) â”€â”€
    emit("validating", "running")
    parts = validate_url(url)
    if not parts.get("valid"):
        state = state_of()
        if state:
            state.update({
                "status": "ERROR",
                "error": parts.get("error"),
                "error_code": parts.get("error_code"),
                "progress": 100,
            })
            emit("validating", "fail", parts.get("error"))
        result = {
            "success": False,
            "scan_id": scan_id,
            "url": url,
            "status": "ERROR",
            "error": parts.get("error") or "Please enter a valid URL.",
            "error_code": parts.get("error_code") or "INVALID_URL",
            "timestamp": timestamp,
            "source": source,
        }
        if on_complete:
            try:
                on_complete(result)
            except Exception:
                pass
        return result

    url = parts["normalized_url"]
    state = state_of()
    if state:
        state["url"] = url
    emit("validating", "done", url)

    # â”€â”€ Stage: RESOLVING DOMAIN â”€â”€
    emit("resolving", "running")
    time.sleep(0.15)  # smooth stage transitions for the live UI
    emit("resolving", "done")

    # â”€â”€ Stage: CHECKING DNS â”€â”€
    emit("dns", "running")
    try:
        _dns, _derr = _run_with_timeout(analyze_dns, args=(url, parts), timeout=15)
        if _dns is not None:
            domain_info = _dns
        else:
            raise TimeoutError("DNS analysis timed out.") if _derr == "timeout" else _derr
    except Exception as e:
        domain_info = {
            "hostname": parts["hostname"], "registered_domain": parts["hostname"],
            "subdomain_count": 0, "subdomains": [], "is_ip_address": False,
            "resolved": False, "ips": [], "ip_address": None,
            "dns_error": f"DNS analysis error ({type(e).__name__}).",
            "whois_available": False, "domain_age": "Information unavailable",
            "registrar": None, "hosting_asn": None, "note": None,
        }
    dns_detail = domain_info.get("ip_address") or domain_info.get("dns_error")
    emit("dns", "done" if domain_info.get("resolved") else "fail", dns_detail)

    # â”€â”€ Stage: ANALYZING SSL/TLS â”€â”€
    emit("ssl", "running")
    try:
        _ssl, _serr = _run_with_timeout(analyze_ssl, args=(url, parts), timeout=15)
        if _ssl is not None:
            ssl_info = _ssl
        else:
            raise TimeoutError("SSL analysis timed out.") if _serr == "timeout" else _serr
    except Exception as e:
        ssl_info = {
            "checked": False, "status": "unreachable",
            "https_enabled": parts["scheme"] == "https",
            "valid": False, "error": f"SSL analysis error ({type(e).__name__}).",
        }
    if ssl_info.get("status") == "valid":
        emit("ssl", "done", ssl_info.get("tls_version") or "valid")
    elif ssl_info.get("status") == "not_https":
        emit("ssl", "skip", "HTTP target")
    else:
        emit("ssl", "fail", ssl_info.get("error"))

    # â”€â”€ Stage: ANALYZING REDIRECTS â”€â”€
    emit("redirects", "running")
    try:
        _redir, _rerr = _run_with_timeout(
            _probe_redirects, args=(url, parts, domain_info), timeout=20)
        if _redir is not None:
            redirect_info = _redir
        else:
            reason = "Redirect probe timed out." if _rerr == "timeout" else f"Redirect probe error ({type(_rerr).__name__})."
            redirect_info = {"chain": [], "note": reason}
    except Exception as e:
        redirect_info = {"chain": [], "note": f"Redirect probe error ({type(e).__name__})."}
    emit("redirects", "fail" if redirect_info.get("blocked") else "done",
         redirect_info.get("block_reason") or f"{len(redirect_info.get('chain', []))} redirect(s)")

    # â”€â”€ Stage: CHECKING DOMAIN INFORMATION â”€â”€
    emit("domain_info", "running")
    emit("domain_info", "done", domain_info.get("registered_domain"))

    # â”€â”€ Stage: CHECKING REPUTATION â”€â”€
    emit("reputation", "running")
    try:
        reputation = check_reputation(url, parts.get("hostname") or "")
    except Exception as e:
        reputation = {
            "available": False, "provider": None,
            "reputation": "Unknown", "malware": "Unknown",
            "phishing": "Unknown", "engines": None,
            "note": f"Reputation check error ({type(e).__name__}).",
        }
    rep_detail = reputation.get("reputation") or reputation.get("note") or "checked"
    emit("reputation", "done" if reputation.get("available") else "skip", rep_detail)

    # â”€â”€ Stages: THREAT INDICATORS + URL STRUCTURE â”€â”€
    emit("threats", "running")
    try:
        findings = detect_threats(url, parts, domain_info, ssl_info, redirect_info)
    except Exception as e:
        findings = [{
            "id": "detector_error", "severity": "INFO", "category": "engine",
            "title": "Threat detector warning",
            "detail": f"Structure checks partially unavailable ({type(e).__name__}).",
            "score_impact": 0, "positive": False,
        }]
    emit("threats", "done", f"{len(findings)} finding(s)")

    # ── ML phishing classifier (offline lexical model, no network) ──
    ml_info = None
    if analyze_url_ml is not None:
        emit("structure", "running", "ML phishing classifier")
        try:
            ml_info = analyze_url_ml(url)
        except Exception as e:
            ml_info = {"available": False,
                       "note": f"ML classifier error ({type(e).__name__})."}
        if ml_info and ml_info.get("available"):
            try:
                _ml_prob = float(ml_info.get("probability") or 0.0)
            except (TypeError, ValueError):
                _ml_prob = 0.0
            if _ml_prob >= 0.55:
                findings.append(_ml_finding(ml_info))
    emit("structure", "done")

    # â”€â”€ Stage: CALCULATING RISK SCORE â”€â”€
    emit("scoring", "running")
    try:
        scored = score_scan(findings, domain_info, ssl_info, reputation,
                            ml_analysis=ml_info)
    except Exception:
        scored = {
            "score": 0, "risk_level": "CRITICAL", "risk_level_label": "CRITICAL",
            "classification": "UNKNOWN", "classification_label": "UNKNOWN",
            "classification_summary": "Unable to Determine",
            "reasoning": ["Scoring engine error â€” treat as unverified."],
        }
    recommendation = build_recommendation(scored["classification"], findings, reputation)
    emit("scoring", "done", f"{scored['score']}/100")

    # â”€â”€ Assemble final payload â”€â”€
    result = _build_result(
        scan_id, url, parts, domain_info, ssl_info, redirect_info,
        reputation, findings, scored, recommendation, timestamp, source,
        ml_info,
    )

    state = state_of()
    if state:
        state.update({
            "status": "COMPLETE",
            "stage": "complete",
            "stage_label": dict(SCAN_STAGES)["complete"],
            "stage_status": "done",
            "progress": 100,
        })
        for s in state.get("stages", []):
            if s["status"] in ("running", "pending"):
                s["status"] = "done"
        state["result"] = result
    emit("complete", "done")

    history.add_entry(result)
    if on_complete:
        try:
            on_complete(result)
        except Exception as _e:
            import traceback as _tb
            print(f"[URL ANALYZER] on_complete callback failed: {_e}")
            _tb.print_exc()
    return result


def _ml_finding(ml_info: dict) -> dict:
    """Convert the ML classifier payload into a transparent finding."""
    prob = float(ml_info.get("probability") or 0.0)
    pct = int(round(prob * 100))
    severity = "CRITICAL" if prob >= 0.90 else ("HIGH" if prob >= 0.75 else "MEDIUM")
    signals = ml_info.get("top_signals") or []
    sig_txt = ""
    if signals:
        names = ", ".join(s.get("feature", "?") for s in signals[:3])
        sig_txt = f" Most influential features: {names}."
    return {
        "id": "ml_phishing_classifier",
        "severity": severity,
        "category": "ml",
        "title": f"ML classifier: {pct}% phishing probability",
        "detail": (
            f"The machine-learning phishing classifier "
            f"({ml_info.get('algorithm') or 'ensemble'}, trained on lexical "
            f"URL patterns) scored this URL at {pct}% phishing probability."
            + sig_txt
        ),
        "score_impact": {"CRITICAL": 40, "HIGH": 22, "MEDIUM": 10}[severity],
        "positive": False,
    }


def _ml_summary_check(ml_info) -> dict:
    """Summary-checklist entry for the ML phishing classifier."""
    if not (ml_info and ml_info.get("available")):
        return {"name": "ML Phishing Model", "status": "warn",
                "detail": "Model unavailable"}
    try:
        prob = float(ml_info.get("probability") or 0.0)
    except (TypeError, ValueError):
        prob = 0.0
    pct = int(round(prob * 100))
    if prob >= 0.55:
        return {"name": "ML Phishing Model", "status": "fail",
                "detail": f"{pct}% phishing probability"}
    if prob >= 0.35:
        return {"name": "ML Phishing Model", "status": "warn",
                "detail": f"Low-confidence result ({pct}%)"}
    return {"name": "ML Phishing Model", "status": "pass",
            "detail": f"No phishing pattern ({100 - pct}% confidence)"}


def _build_result(scan_id, url, parts, domain_info, ssl_info, redirect_info,
                  reputation, findings, scored, recommendation, timestamp,
                  source, ml_info=None) -> dict:
    """Assemble the final structured result payload for UI/report/voice."""
    hostname = parts.get("hostname") or ""
    dom = split_domain(hostname)
    chain = redirect_info.get("chain") or []

    # Scan summary checklist for the UI
    ssl_status = ssl_info.get("status")
    summary_checks = [
        {"name": "URL Format", "status": "pass"},
        {"name": "HTTPS",
         "status": "pass" if parts.get("scheme") == "https" else "fail",
         "detail": None if parts.get("scheme") == "https" else "Plain HTTP"},
        {"name": "SSL Certificate",
         "status": ("pass" if ssl_status == "valid"
                    else ("skip" if ssl_status == "not_https" else "fail")),
         "detail": None if ssl_status == "valid" else (ssl_info.get("error") or None)},
        {"name": "DNS Resolution",
         "status": "pass" if domain_info.get("resolved") else "fail",
         "detail": domain_info.get("dns_error")},
        {"name": "Domain Reputation",
         "status": "pass" if reputation.get("available") else "warn",
         "detail": None if reputation.get("available") else "Reputation data unavailable"},
        {"name": "Domain Age",
         "status": "warn" if not domain_info.get("whois_available") else "pass",
         "detail": "Information unavailable" if not domain_info.get("whois_available") else None},
    ]
    summary_checks.append(_ml_summary_check(ml_info))

    result = {
        "success": True,
        "scan_id": scan_id,
        "url": url,
        "display_url": url if len(url) <= 80 else url[:77] + "...",
        "hostname": hostname,
        "domain_display": dom["registered_domain"],
        "score": scored["score"],
        "risk_level": scored["risk_level"],
        "risk_level_label": scored["risk_level_label"],
        "classification": scored["classification"],
        "classification_label": scored["classification_label"],
        "classification_summary": scored["classification_summary"],
        "reasoning": scored["reasoning"],
        "ml_phishing": ml_info or {"available": False,
                                   "note": "ML classifier unavailable"},
        "summary": {"checks": summary_checks},
        "url_details": {
            "protocol": (parts.get("scheme") or "").upper(),
            "domain": hostname,
            "registered_domain": dom["registered_domain"],
            "subdomain_count": dom["subdomain_count"],
            "ip_address": domain_info.get("ip_address"),
            "ips": domain_info.get("ips") or [],
            "port": parts.get("port"),
            "path": parts.get("path") or "/",
            "query": parts.get("query"),
            "fragment": parts.get("fragment"),
            "redirects": len(chain),
            "redirect_chain": chain,
            "final_url": redirect_info.get("final_url"),
        },
        "ssl": ssl_info,
        "domain": domain_info,
        "reputation": reputation,
        "findings": findings,
        "recommendation": recommendation,
        "timestamp": timestamp,
        "timestamp_display": datetime.now().strftime("%d %b %Y %H:%M"),
        "source": source,
    }
    return result


def _voice_summary_text(result: dict) -> str:
    """
    Voice-friendly spoken response after an analysis, per the ZYRA spec:

      "The URL analysis is complete. The website received a safety score of
       92 out of 100 and no significant malicious indicators were detected."

      "The URL analysis is complete. The website has been classified as high
       risk with a safety score of 18 out of 100. Malicious indicators were
       detected."
    """
    if not result:
        return "The URL analysis could not be completed."
    if not result.get("success"):
        err = result.get("error") or "The URL could not be analyzed."
        return f"The URL analysis failed. {err}"

    score = result.get("score", 0)
    classification = result.get("classification", "UNKNOWN")
    domain = result.get("domain_display") or "the website"

    if classification == "MALICIOUS":
        risk = str(result.get("risk_level_label", "HIGH")).lower().replace("_", " ")
        return (
            f"The URL analysis is complete. The website has been classified as "
            f"{risk} risk with a safety score of {score} out of 100. "
            f"Malicious indicators were detected. Do not open this link or "
            f"enter any personal information."
        )
    if classification == "SUSPICIOUS":
        risk = str(result.get("risk_level_label", "MEDIUM")).lower().replace("_", " ")
        return (
            f"The URL analysis is complete. {domain} has been classified as "
            f"suspicious with a safety score of {score} out of 100 and "
            f"{risk} risk. Please review the detailed findings before "
            f"opening it."
        )
    if classification == "UNKNOWN":
        return (
            f"The URL analysis is complete, but there is insufficient "
            f"information to confidently classify this website. The safety "
            f"score is {score} out of 100. Proceed with caution."
        )
    return (
        f"The URL analysis is complete. The website received a safety score "
        f"of {score} out of 100 and no significant malicious indicators were "
        f"detected. Always verify the destination before entering "
        f"credentials."
    )

def build_voice_summary(result: dict) -> str:
    """
    Voice summary with an ML sentence appended when the phishing classifier
    flagged the URL (probability >= 55%).
    """
    text = _voice_summary_text(result)
    ml = (result or {}).get("ml_phishing") or {}
    if ml.get("available"):
        try:
            prob = float(ml.get("probability") or 0.0)
        except (TypeError, ValueError):
            prob = 0.0
        if prob >= 0.55:
            text += (
                f" The machine learning classifier also estimates a "
                f"{int(round(prob * 100))} percent phishing probability."
            )
    return text


def get_last_scan():
    """Most recent scan state id, or None."""
    with _LOCK:
        if _SCANS:
            return next(reversed(_SCANS))
    return None


def get_history(limit: int = 8):
    return history.recent(limit)


def _stage_update(stage_key: str, status: str = "running",
                  detail: str = None) -> dict:
    """Build the broadcast payload for a stage transition."""
    label = dict(SCAN_STAGES).get(stage_key, stage_key.upper())
    return {
        "stage": stage_key,
        "stage_label": label,
        "stage_status": status,
        "stage_detail": detail,
        "progress": STAGE_PROGRESS.get(stage_key, 0),
    }
