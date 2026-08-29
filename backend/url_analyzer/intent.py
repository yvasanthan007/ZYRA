"""
backend/url_analyzer/intent.py — URL_ANALYSIS intent detection

Detects the URL_ANALYSIS intent in chat / voice text and extracts the
target URL automatically, reusing ZYRA's existing URL extraction engine
(backend/link_security.py) as the canonical extractor.

Supported commands (chat or voice):
    "Analyze https://example.com"
    "Analyze this URL https://example.com"
    "Check whether https://example.com is safe"
    "Is this website malicious?"
    "Scan this URL"
    "Check this website for phishing"
    "Analyze https://example.com for threats"
    "Is this link safe?"
    ...or a bare URL, which triggers an analysis automatically.
"""

import re

from backend.link_security import extract_url  # existing canonical extractor

# Explicit analysis verbs / triggers
_ANALYSIS_TRIGGERS = [
    "analyze", "analyse", "check", "scan", "inspect", "verify",
    "is it safe", "is this safe", "is it malicious", "is this malicious",
    "is it legit", "is this legit", "is it secure", "is this secure",
    "is it trustworthy", "is this trustworthy", "any threats",
    "phishing", "threats", "dangerous", "reputation",
]

# Target nouns that identify WHAT should be analyzed
_URL_NOUNS = [
    "url", "link", "website", "site", "web page", "webpage", "page",
    "domain", "this", "that", "it",
]

_BARE_URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)


def is_url_analysis_intent(text: str) -> bool:
    """
    True when the message should activate the URL Analyzer.

    Rules:
      - A URL is present AND any analysis trigger/verb appears, OR
      - a URL is present AND an analysis noun appears ("scan this url"), OR
      - an explicit 'safe/malicious/phishing' question about a link/site,
        even without a URL in the text (user will be asked for the URL).
    """
    if not text:
        return False
    t = text.lower().strip()

    has_url = extract_url(t) is not None or bool(_BARE_URL_RE.search(t))
    has_trigger = any(k in t for k in _ANALYSIS_TRIGGERS)
    has_noun = any(k in t for k in _URL_NOUNS)

    if has_url and has_trigger:
        return True
    if has_url and has_noun and any(k in t for k in ("safe", "malicious", "phishing", "threat", "check", "scan", "analyze", "analyse")):
        return True
    # No URL but a clear link-safety question → intent without target
    if not has_url and has_trigger and has_noun:
        return True
    return False


def extract_target_url(text: str):
    """Extract the first analyzable URL from the text, or None."""
    if not text:
        return None
    url = extract_url(text)
    if url:
        return url
    match = _BARE_URL_RE.search(text)
    if match:
        return match.group(0).rstrip(".,!?;:'\"")
    return None


def build_chat_ack(target_url) -> str:
    """
    Chat acknowledgement sent by ZYRA when the URL_ANALYSIS intent fires.
    With a URL: activation notice (panel opens + scan runs).
    Without: a short request for the URL.
    """
    if target_url:
        return (
            "URL ANALYZER ACTIVATED\n"
            f"Target: {target_url}\n"
            "Scanning... running real-time security checks: URL validation, "
            "DNS, SSL/TLS, domain information, reputation, threat indicators "
            "and risk scoring."
        )
    return (
        "URL ANALYZER ACTIVATED. Please provide the URL you'd like me to "
        "analyze — for example: \"Analyze https://example.com\"."
    )
