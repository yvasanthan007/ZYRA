"""
backend/threat_intel.py — shared VirusTotal threat-intelligence client.

A single, correct code path that BOTH ZYRA phishing-detection surfaces use so
link analysis and the URL Analyzer always agree:

    * Link analysis  -> link_analysis.py / backend/link_security.py
    * URL Analyzer   -> backend/url_analyzer/reputation.py

Key behaviours (fixing the previous integration):
  * The API key is read from ``VIRUSTOTAL_API_KEY`` (falling back to
    ``THREAT_INTEL_API_KEY``). A project-root ``.env`` file is loaded
    automatically (python-dotenv) when available, so the key can simply be
    dropped in ``.env`` without touching code.
  * :func:`check_url` SUBMITS the URL for a fresh scan when it is not already
    in VirusTotal's corpus and then POLLS the analysis until it completes
    (bounded wait) instead of the old "submit then immediately read an empty
    analysis" behaviour that always looked safe.
  * Every failure degrades gracefully to ``{"available": False, ...}`` — the
    client never raises into a scan and never reports "safe" on an error.
"""

import base64
import os
import time
from typing import Optional

import requests

VT_BASE = "https://www.virustotal.com/api/v3"
VT_SUBMIT_URL = f"{VT_BASE}/urls"
VT_ANALYSIS_URL = f"{VT_BASE}/analyses/"
VT_URL_INFO_URL = f"{VT_BASE}/urls/"

REQUEST_TIMEOUT = 10          # seconds per HTTP request
DEFAULT_MAX_WAIT = 25         # seconds to wait for an analysis to complete
DEFAULT_POLL_INTERVAL = 5     # seconds between analysis polls

_USER_AGENT = "ZYRA-ThreatIntel/1.0"

_ENV_LOADED = False


# ──────────────────────────────────────────────
# Environment / configuration
# ──────────────────────────────────────────────

def load_env() -> None:
    """
    Load a project-root ``.env`` file (once) so API keys work without code
    changes. Safe to call from anywhere; a missing file or missing
    python-dotenv is ignored.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    try:
        # project root = two levels up from backend/threat_intel.py
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for candidate in (os.path.join(root, ".env"),
                          os.path.join(os.getcwd(), ".env")):
            if os.path.exists(candidate):
                load_dotenv(candidate, override=False)
    except Exception:
        pass


def _env(key: str) -> Optional[str]:
    value = os.environ.get(key)
    return value.strip() if value and value.strip() else None


def get_api_key() -> Optional[str]:
    """The configured VirusTotal API key, or None."""
    load_env()
    return _env("VIRUSTOTAL_API_KEY") or _env("THREAT_INTEL_API_KEY")


def is_configured() -> bool:
    """True when a VirusTotal API key is available."""
    return bool(get_api_key())


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _url_id(url: str) -> str:
    """VirusTotal v3 URL identifier (urlsafe base64 without padding)."""
    return base64.urlsafe_b64encode(url.encode()).decode().strip("=")


def _unavailable(note: str, provider: Optional[str] = None) -> dict:
    return {
        "available": False,
        "provider": provider,
        "reputation": "Unknown",
        "malware": "Unknown",
        "phishing": "Unknown",
        "engines": None,
        "note": note,
    }


def _classify(stats: dict) -> dict:
    """Map VirusTotal ``last_analysis_stats`` to a structured reputation."""
    malicious = int(stats.get("malicious", 0) or 0)
    suspicious = int(stats.get("suspicious", 0) or 0)
    harmless = int(stats.get("harmless", 0) or 0)
    undetected = int(stats.get("undetected", 0) or 0)
    total = int(stats.get("total", 0) or (malicious + suspicious + harmless + undetected))

    if malicious > 0:
        reputation, malware, phishing = "Malicious", "Detected", "Detected"
    elif suspicious > 0:
        reputation, malware, phishing = "Suspicious", "Unknown", "Unknown"
    elif (harmless + undetected) > 0:
        reputation, malware, phishing = "Clean", "Not Detected", "Not Detected"
    else:
        reputation, malware, phishing = "Unknown", "Unknown", "Unknown"

    return {
        "available": True,
        "provider": "virustotal",
        "reputation": reputation,
        "malware": malware,
        "phishing": phishing,
        "engines": {
            "malicious": malicious,
            "suspicious": suspicious,
            "harmless": harmless,
            "undetected": undetected,
            "total": total,
        },
        "note": (
            f"VirusTotal: {malicious} malicious / {suspicious} suspicious "
            f"of {total} engines."
            if total else "VirusTotal analysis completed with no engine data."
        ),
    }


def _get_url_info(url_id: str, headers: dict) -> Optional[dict]:
    """Fetch an existing report's ``last_analysis_stats`` (may be None)."""
    try:
        resp = requests.get(VT_URL_INFO_URL + url_id, headers=headers,
                            timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        attrs = resp.json().get("data", {}).get("attributes", {})
    except ValueError:
        return None
    return attrs.get("last_analysis_stats") or None


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def check_url(url: str, max_wait: int = DEFAULT_MAX_WAIT,
              poll_interval: int = DEFAULT_POLL_INTERVAL) -> dict:
    """
    Look up *url* on VirusTotal, submitting it for a fresh scan when needed.

    Returns a structured dict:
        {"available": bool, "provider", "reputation", "malware", "phishing",
         "engines", "note"}

    ``available`` is False only when no key is configured or the request
    failed — in which case the caller must NOT treat the URL as safe.
    """
    url = str(url or "").strip()
    if not url:
        return _unavailable("No URL supplied for reputation lookup.")

    api_key = get_api_key()
    if not api_key:
        return _unavailable(
            "Reputation data unavailable — set VIRUSTOTAL_API_KEY in .env "
            "to enable VirusTotal scanning."
        )

    headers = {"x-apikey": api_key, "User-Agent": _USER_AGENT}
    url_id = _url_id(url)

    try:
        # 1. Existing report first — instant when the URL is already known.
        stats = _get_url_info(url_id, headers)
        if stats:
            return _classify(stats)

        # 2. Not in the corpus: submit it for a fresh analysis.
        submit = requests.post(VT_SUBMIT_URL, headers=headers,
                               data={"url": url}, timeout=REQUEST_TIMEOUT)
        if submit.status_code in (401, 403):
            return _unavailable(
                "Reputation data unavailable — VirusTotal rejected the API "
                "key (invalid or unauthorised)."
            )
        if submit.status_code == 429:
            return _unavailable(
                "VirusTotal rate limit reached — try again shortly."
            )
        submit.raise_for_status()
        analysis_id = submit.json().get("data", {}).get("id", "")
        if not analysis_id:
            stats = _get_url_info(url_id, headers)
            return _classify(stats) if stats else _unavailable(
                "VirusTotal accepted the URL but returned no analysis id."
            )

        # 3. Poll the analysis until it completes (bounded wait).
        deadline = time.time() + max(5, max_wait)
        while time.time() < deadline:
            try:
                an = requests.get(VT_ANALYSIS_URL + analysis_id, headers=headers,
                                  timeout=REQUEST_TIMEOUT)
            except requests.exceptions.RequestException:
                break
            if an.status_code != 200:
                break
            try:
                attrs = an.json().get("data", {}).get("attributes", {})
            except ValueError:
                break
            stats = attrs.get("stats")
            if attrs.get("status") == "completed" and stats:
                return _classify(stats)
            if stats and attrs.get("status") in ("completed", "failure"):
                return _classify(stats)
            time.sleep(poll_interval)

        # 4. Timed out polling — use any report that appeared in the meantime.
        stats = _get_url_info(url_id, headers)
        if stats:
            return _classify(stats)
        return _unavailable(
            "VirusTotal scan submitted but not finished within the time "
            "budget; result not verified."
        )

    except requests.exceptions.Timeout:
        return _unavailable("VirusTotal request timed out.")
    except requests.exceptions.RequestException as exc:
        return _unavailable(f"VirusTotal request failed ({type(exc).__name__}).")
    except Exception as exc:  # noqa: BLE001 — never break a scan
        return _unavailable(f"VirusTotal lookup error ({type(exc).__name__}).")


def provider_status(probe: bool = True) -> dict:
    """
    Report whether VirusTotal is configured and (optionally) reachable.
    Used by the dashboard/CLI connectivity check.
    """
    key = get_api_key()
    if not key:
        return {
            "configured": False,
            "reachable": False,
            "provider": None,
            "note": "No VirusTotal API key configured (set VIRUSTOTAL_API_KEY).",
        }
    if not probe:
        return {"configured": True, "reachable": None, "provider": "virustotal",
                "note": "Key configured (reachability not probed)."}
    try:
        resp = requests.get(VT_URL_INFO_URL + _url_id("https://www.google.com"),
                            headers={"x-apikey": key, "User-Agent": _USER_AGENT},
                            timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        return {"configured": True, "reachable": False, "provider": "virustotal",
                "note": f"Key configured but VirusTotal unreachable "
                        f"({type(exc).__name__})."}
    if resp.status_code in (200, 404):
        return {"configured": True, "reachable": True, "provider": "virustotal",
                "note": "VirusTotal API key is valid and reachable."}
    if resp.status_code in (401, 403):
        return {"configured": True, "reachable": False, "provider": "virustotal",
                "note": "VirusTotal rejected the API key (401/403)."}
    if resp.status_code == 429:
        return {"configured": True, "reachable": True, "provider": "virustotal",
                "note": "Reachable — rate limit hit (429)."}
    return {"configured": True, "reachable": False, "provider": "virustotal",
            "note": f"Unexpected VirusTotal status {resp.status_code}."}
