"""
backend/link_intel.py — shared threat-intelligence evidence for link analysis.

Role
    One bounded, cached, failure-tolerant entry point for "what does VirusTotal
    know about this URL?", plus the fusion rule that turns the collected
    evidence (VirusTotal + local ML + heuristic findings) into a single verdict.

Why a separate module
    The link analyzer (`backend/link_security.py`, `backend/url_analyzer`) and
    the ML endpoint (`/api/ml/phishing`) all need the same reputation data. They
    previously each called VirusTotal directly, which meant:

      * no caching — checking the same link twice (e.g. once by voice and once
        by the desktop UI) spent two API calls against the free-tier quota
        (4 requests / minute), so the second check usually failed with 429;
      * unbounded latency — a brand-new URL is submitted for a fresh analysis
        and polled, which can take many seconds or hang the caller;
      * inconsistent results — each caller interpreted the reply differently.

    This module fixes all three. It never raises: a missing key, a quota
    rejection or a network failure all produce a structured "unavailable"
    record, and callers must treat that as UNVERIFIED (never as safe).

Verdict fusion
    `fuse_verdict()` is the single place where evidence becomes a decision. The
    rule is deliberately conservative: authoritative detections (VirusTotal)
    always win, independent sources corroborating each other escalate the
    verdict, and absence of evidence never downgrades a heuristic finding.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

def _env_float(key: str, default: float, low: float = 0.0, high: float = 600.0) -> float:
    try:
        return max(low, min(high, float(os.environ.get(key, default))))
    except (TypeError, ValueError):
        return default


# How long a completed VirusTotal answer stays valid. A reputation does not
# change meaningfully within minutes, so re-checking the same link (voice, then
# UI, then a re-open) is served from memory and costs no API calls.
CACHE_TTL_SECONDS = _env_float("ZYRA_VT_CACHE_TTL", 600.0, 0.0, 86400.0)

# How long an "unavailable" answer (no key / 429 / timeout) is remembered.
# Short, so a quota reset or a restored connection recovers quickly, but long
# enough that a burst of checks does not hammer a rate-limited API.
FAILURE_CACHE_TTL_SECONDS = _env_float("ZYRA_VT_FAILURE_CACHE_TTL", 30.0, 0.0, 600.0)

# Hard wall-clock budget for one reputation lookup. This is the number that
# bounds how long "Analyze this link" can take when VirusTotal is slow.
LOOKUP_BUDGET_SECONDS = _env_float("ZYRA_VT_LOOKUP_BUDGET", 8.0, 1.0, 60.0)

# VirusTotal free tier allows 4 requests/minute. When a caller needs a fast
# answer it passes a shorter ``budget``; the cache makes that affordable.
_MAX_CACHE_ENTRIES = 256

_lock = threading.Lock()
_cache: Dict[str, Dict[str, Any]] = {}


# ──────────────────────────────────────────────
# Normalisation
# ──────────────────────────────────────────────

def _normalize(url: str) -> str:
    """Cache key: a stable form so trivial variations share one lookup."""
    text = str(url or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    # A scheme-less link and its https:// form are the same resource.
    if "://" not in lowered:
        lowered = "https://" + lowered
    # Fragments never reach the server and do not change the resource.
    return lowered.split("#", 1)[0]


def clear_cache() -> None:
    """Drop all cached reputation answers (used by tests and 'retry' paths)."""
    with _lock:
        _cache.clear()


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if not hit:
            return None
        ttl = hit["ttl"]
        if ttl <= 0 or now - hit["ts"] > ttl:
            _cache.pop(key, None)
            return None
        entry = dict(hit["value"])
    entry["cached"] = True
    entry["cached_age_seconds"] = round(now - hit["ts"], 1)
    return entry


def _cache_put(key: str, value: Dict[str, Any]) -> None:
    if not key:
        return
    ttl = CACHE_TTL_SECONDS if value.get("available") else FAILURE_CACHE_TTL_SECONDS
    now = time.time()
    with _lock:
        _cache[key] = {"ts": now, "ttl": ttl, "value": dict(value)}
        if len(_cache) > _MAX_CACHE_ENTRIES:
            # Drop the oldest entries first.
            for old_key, _ in sorted(_cache.items(), key=lambda kv: kv[1]["ts"])[
                : len(_cache) - _MAX_CACHE_ENTRIES
            ]:
                _cache.pop(old_key, None)


def _reset_lookup_clock() -> None:
    """Test hook: forget the last lookup time so a new lookup may start now."""
    global _last_lookup
    with _lock:
        _last_lookup = 0.0


_last_lookup = 0.0
# Serialises actual lookups: the free tier rejects bursts, and two concurrent
# checks of the same URL would otherwise both submit a fresh analysis.
_lookup_lock = threading.Lock()


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def lookup(url: str, budget: Optional[float] = None) -> Dict[str, Any]:
    """
    Return VirusTotal evidence for *url*, bounded by a wall-clock budget.

    Always returns a dict with at least:
        available : bool        — False means UNVERIFIED, never "safe"
        provider  : "virustotal"
        reputation: "Malicious" | "Suspicious" | "Clean" | "Unknown"
        engines   : {malicious, suspicious, harmless, undetected, total} | None
        note      : human-readable explanation
        source    : "cache" | "virustotal"
        latency_ms: how long the lookup took
        verdict_hint: "MALICIOUS" | "SUSPICIOUS" | "CLEAN" | "UNKNOWN"

    Never raises.
    """
    started = time.perf_counter()
    key = _normalize(url)
    if not key:
        return _record(False, "No URL supplied for a reputation lookup.",
                       started=started, hint="UNKNOWN")

    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        from backend import threat_intel
    except Exception as exc:  # pragma: no cover — defensive
        return _record(False,
                       f"Reputation client unavailable ({type(exc).__name__}).",
                       started=started, hint="UNKNOWN")

    if not threat_intel.is_configured():
        result = _record(
            False,
            "Reputation data unavailable — set VIRUSTOTAL_API_KEY in .env to "
            "enable multi-engine threat checking.",
            started=started,
            hint="UNKNOWN",
        )
        _cache_put(key, result)
        return result

    deadline = time.time() + (LOOKUP_BUDGET_SECONDS if budget is None else budget)
    acquired = _await_lock(deadline)
    if not acquired:
        return _record(False, "Reputation lookup is busy; this URL was not re-checked.",
                       started=started, hint="UNKNOWN")

    try:
        # Re-check the cache: the lookup we waited behind may have filled it.
        cached = _cache_get(key)
        if cached is not None:
            return cached

        remaining = max(0.5, deadline - time.time())
        try:
            raw = threat_intel.check_url(key, max_wait=remaining, poll_interval=1)
        except TypeError:
            # Older signature without keyword support — still bounded by timeout.
            raw = threat_intel.check_url(key)
        except Exception as exc:  # noqa: BLE001 — never break a caller
            raw = {"available": False,
                   "note": f"VirusTotal lookup error ({type(exc).__name__})."}

        result = _from_threat_intel(raw, started)
    finally:
        try:
            _lookup_lock.release()
        except RuntimeError:
            pass

    _cache_put(key, result)
    return result


def _await_lock(deadline: float) -> bool:
    """Acquire the lookup lock, giving up at *deadline* (never blocks forever)."""
    global _last_lookup
    while True:
        wait = deadline - time.time()
        if wait <= 0:
            return False
        if _lookup_lock.acquire(timeout=min(wait, 0.5)):
            _last_lookup = time.time()
            return True


def _from_threat_intel(raw: Optional[Dict[str, Any]], started: float) -> Dict[str, Any]:
    """Convert the threat_intel payload into the compact evidence record."""
    if not isinstance(raw, dict) or not raw.get("available"):
        note = (raw or {}).get("note") or "Reputation could not be verified."
        return _record(False, str(note), started=started, hint="UNKNOWN")

    engines = raw.get("engines") or {}
    try:
        malicious = int(engines.get("malicious") or 0)
        suspicious = int(engines.get("suspicious") or 0)
        total = int(engines.get("total") or 0)
    except (TypeError, ValueError):
        malicious = suspicious = total = 0

    reputation = str(raw.get("reputation") or "Unknown")
    if malicious > 0:
        hint = "MALICIOUS"
    elif suspicious > 0:
        hint = "SUSPICIOUS"
    elif total > 0:
        hint = "CLEAN"
    else:
        hint = "UNKNOWN"

    record = _record(True, str(raw.get("note") or ""), started=started, hint=hint)
    record.update({
        "reputation": reputation,
        "malware": raw.get("malware", "Unknown"),
        "phishing": raw.get("phishing", "Unknown"),
        "engines": {
            "malicious": malicious,
            "suspicious": suspicious,
            "harmless": int(engines.get("harmless") or 0),
            "undetected": int(engines.get("undetected") or 0),
            "total": total,
        },
    })
    return record


def _record(available: bool, note: str, started: float, hint: str) -> Dict[str, Any]:
    return {
        "available": bool(available),
        "provider": "virustotal",
        "reputation": "Unknown",
        "malware": "Unknown",
        "phishing": "Unknown",
        "engines": None,
        "note": note,
        "verdict_hint": hint,
        "source": "virustotal",
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "cached": False,
    }


def status() -> Dict[str, Any]:
    """Configuration + cache summary (for diagnostics endpoints)."""
    try:
        from backend import threat_intel
        configured = threat_intel.is_configured()
    except Exception:
        configured = False
    with _lock:
        cached_entries = len(_cache)
    return {
        "configured": configured,
        "provider": "virustotal" if configured else None,
        "cache_entries": cached_entries,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "lookup_budget_seconds": LOOKUP_BUDGET_SECONDS,
        "note": ("VirusTotal multi-engine reputation active."
                 if configured else
                 "No VIRUSTOTAL_API_KEY configured — reputation is unverified."),
    }


# ──────────────────────────────────────────────
# Verdict fusion
# ──────────────────────────────────────────────

def fuse_verdict(
    verdict: str,
    risk_score: str,
    risk_points: int,
    reputation: Optional[Dict[str, Any]] = None,
    ml_probability: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Combine heuristic + ML + VirusTotal evidence into the final verdict.

    Rules (highest authority first):
      1. VirusTotal reports any malicious engine  -> PHISHING DETECTED / Critical.
      2. VirusTotal reports suspicious engines AND the local engine already
         flagged the link (risk >= 3) or the ML model agrees (>= 0.55)
         -> PHISHING DETECTED / High (two independent sources agree).
      3. VirusTotal reports suspicious engines alone -> at least SUSPICIOUS.
      4. No VirusTotal evidence NEVER downgrades anything: the heuristic/ML
         verdict stands, and the level is capped at HIGH so an unverified link
         is not presented as certain.

    Returns {"verdict", "risk_score", "escalated_by", "reasons"}.
    """
    rep = reputation or {}
    hint = str(rep.get("verdict_hint") or "UNKNOWN").upper()
    engines = rep.get("engines") or {}
    malicious = int(engines.get("malicious") or 0)
    suspicious = int(engines.get("suspicious") or 0)
    total = int(engines.get("total") or 0)
    reasons = []
    escalated_by = None

    level_rank = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    final_verdict, final_level = verdict, risk_score

    if hint == "MALICIOUS" and malicious > 0:
        final_verdict, final_level = "PHISHING DETECTED", "Critical"
        escalated_by = "virustotal"
        reasons.append(
            f"VirusTotal: {malicious} of {total} security engines flag this URL as malware/phishing."
        )
    elif hint == "SUSPICIOUS" and suspicious > 0:
        corroborated = risk_points >= 3 or (ml_probability is not None and ml_probability >= 0.55)
        if corroborated:
            final_verdict = "PHISHING DETECTED"
            final_level = "High" if level_rank.get(final_level, 0) <= level_rank["High"] else final_level
            escalated_by = "virustotal+local"
            reasons.append(
                f"VirusTotal: {suspicious} of {total} engines flag this URL as suspicious, "
                "and ZYRA's own analysis agrees."
            )
        else:
            if level_rank.get(final_level, 0) < level_rank["Medium"]:
                final_verdict, final_level = "SUSPICIOUS", "Medium"
            escalated_by = "virustotal"
            reasons.append(
                f"VirusTotal: {suspicious} of {total} engines flag this URL as suspicious."
            )
    elif hint == "CLEAN" and total > 0:
        reasons.append(
            f"VirusTotal: no detections across {total} engines — corroborates the "
            "local analysis, but is not proof of safety."
        )
    else:
        if level_rank.get(final_level, 0) > level_rank["High"]:
            final_level = "High"
        reasons.append(
            "VirusTotal reputation could not be verified — the verdict relies on "
            "ZYRA's local analysis only."
        )

    return {
        "verdict": final_verdict,
        "risk_score": final_level,
        "escalated_by": escalated_by,
        "reasons": reasons,
    }


def summary_line(reputation: Optional[Dict[str, Any]]) -> str:
    """
    One-line human-readable reputation summary for reports and speech.

    ASCII-only punctuation: this string is spoken by TTS, printed to Windows
    consoles and shown in the dashboard, where a Unicode em dash can degrade to
    mojibake (cp1252) or confuse the speech sanitiser.
    """
    rep = reputation or {}
    if not rep.get("available"):
        note = rep.get("note") or "unverified"
        return f"VirusTotal: unavailable ({note})"
    engines = rep.get("engines") or {}
    return (f"VirusTotal: {rep.get('reputation', 'Unknown')} - "
            f"{int(engines.get('malicious') or 0)} malicious / "
            f"{int(engines.get('suspicious') or 0)} suspicious of "
            f"{int(engines.get('total') or 0)} engines")
