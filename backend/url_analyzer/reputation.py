"""
backend/url_analyzer/reputation.py — Threat-intelligence reputation checks

Pluggable reputation providers configured ONLY through environment
variables — API keys are never hard-coded and never exposed to the
frontend.

Supported providers (auto-detected by default):
    VIRUSTOTAL_API_KEY              → VirusTotal v3 URL analysis
    GOOGLE_SAFE_BROWSING_API_KEY    → Google Safe Browsing v4 lookup
    THREAT_INTEL_PROVIDER           → force one: virustotal | google_safe_browsing | none
    THREAT_INTEL_API_KEY            → generic key (used by the forced provider)

When no provider is configured the module returns available=False with the
note "Reputation data unavailable" — the analyzer then reports the URL as
UNKNOWN rather than pretending it is safe.
"""

import base64
import os
from typing import Optional

import requests

from backend.url_analyzer.validator import REQUEST_TIMEOUT

_VT_URL_ENDPOINT = "https://www.virustotal.com/api/v3/urls/"
_GSB_ENDPOINT = "https://safebrowsing.googleapis.com/v4/threatMatches:find"


def _env(key: str) -> Optional[str]:
    value = os.environ.get(key)
    return value.strip() if value and value.strip() else None


def _unavailable(note: str) -> dict:
    return {
        "available": False,
        "provider": None,
        "reputation": "Unknown",
        "malware": "Unknown",
        "phishing": "Unknown",
        "engines": None,
        "note": note,
    }


def get_configured_provider() -> Optional[str]:
    """Name of the threat-intel provider to use, or None when unconfigured."""
    forced = (_env("THREAT_INTEL_PROVIDER") or "").lower()
    if forced == "none":
        return None
    if forced == "virustotal" or (not forced and _env("VIRUSTOTAL_API_KEY")):
        if _env("VIRUSTOTAL_API_KEY") or _env("THREAT_INTEL_API_KEY"):
            return "virustotal"
        return None
    if forced == "google_safe_browsing":
        if _env("GOOGLE_SAFE_BROWSING_API_KEY") or _env("THREAT_INTEL_API_KEY"):
            return "google_safe_browsing"
        return None
    if _env("GOOGLE_SAFE_BROWSING_API_KEY"):
        return "google_safe_browsing"
    if _env("VIRUSTOTAL_API_KEY"):
        return "virustotal"
    return None


def check_reputation(url: str, hostname: str) -> dict:
    """
    Query the configured threat-intelligence provider for the URL.

    Always returns a structured dict; network errors degrade gracefully to
    available=False instead of raising into the scan pipeline.
    """
    provider = get_configured_provider()
    if provider is None:
        return _unavailable(
            "Reputation data unavailable — no threat intelligence provider "
            "configured (set THREAT_INTEL_PROVIDER / THREAT_INTEL_API_KEY)."
        )
    try:
        if provider == "virustotal":
            return _check_virustotal(url)
        if provider == "google_safe_browsing":
            return _check_safe_browsing(url)
        return _unavailable(f"Unknown threat intelligence provider: {provider}")
    except requests.exceptions.Timeout:
        return _unavailable(
            "Threat intelligence provider unavailable. "
            "Reputation score could not be verified (request timed out)."
        )
    except Exception as e:  # never crash the scan on provider errors
        return _unavailable(
            "Threat intelligence provider unavailable. "
            f"Reputation score could not be verified ({type(e).__name__})."
        )


# ──────────────────────────────────────────────
# VirusTotal v3
# ──────────────────────────────────────────────

def _check_virustotal(url: str) -> dict:
    api_key = _env("VIRUSTOTAL_API_KEY") or _env("THREAT_INTEL_API_KEY")
    if not api_key:
        return _unavailable("Reputation data unavailable — VirusTotal API key missing.")

    url_id = base64.urlsafe_b64encode(url.encode()).decode().strip("=")
    resp = requests.get(
        _VT_URL_ENDPOINT + url_id,
        headers={"x-apikey": api_key, "User-Agent": "ZYRA-URL-Analyzer/1.0"},
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 404:
        return {
            "available": True, "provider": "virustotal",
            "reputation": "Unknown", "malware": "Unknown", "phishing": "Unknown",
            "engines": None,
            "note": "URL is not present in the VirusTotal corpus yet.",
        }
    resp.raise_for_status()
    data = resp.json().get("data", {})
    attrs = data.get("attributes", {})
    stats = attrs.get("last_analysis_stats", {}) or {}
    malicious = int(stats.get("malicious", 0) or 0)
    suspicious = int(stats.get("suspicious", 0) or 0)
    harmless = int(stats.get("harmless", 0) or 0)
    undetected = int(stats.get("undetected", 0) or 0)

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
        },
        "note": None,
    }


# ──────────────────────────────────────────────
# Google Safe Browsing v4
# ──────────────────────────────────────────────

def _check_safe_browsing(url: str) -> dict:
    api_key = _env("GOOGLE_SAFE_BROWSING_API_KEY") or _env("THREAT_INTEL_API_KEY")
    if not api_key:
        return _unavailable("Reputation data unavailable — Safe Browsing API key missing.")

    body = {
        "client": {"clientId": "zyra-url-analyzer", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": [
                "MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                "POTENTIALLY_HARMFUL_APPLICATION",
            ],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    resp = requests.post(
        _GSB_ENDPOINT,
        params={"key": api_key},
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    matches = resp.json().get("matches", []) or []

    if not matches:
        return {
            "available": True, "provider": "google_safe_browsing",
            "reputation": "Clean", "malware": "Not Detected",
            "phishing": "Not Detected", "engines": None,
            "note": "No threats found in the Google Safe Browsing index.",
        }

    types = sorted({m.get("threatType", "") for m in matches})
    malware = "Detected" if any("MALWARE" in t or "HARMFUL" in t for t in types) else "Not Detected"
    phishing = "Detected" if any("SOCIAL_ENGINEERING" in t for t in types) else "Not Detected"
    return {
        "available": True, "provider": "google_safe_browsing",
        "reputation": "Malicious", "malware": malware, "phishing": phishing,
        "engines": {"threat_types": types},
        "note": "Threats found in the Google Safe Browsing index.",
    }

