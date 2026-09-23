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

# Safety-verdict words: when a URL is present together with one of these the
# message is a link-safety question even without a dedicated verb
# ("Is https://example.com safe?", "Is this website malicious?").
_SAFETY_QUESTION_WORDS = [
    "safe", "unsafe", "suspicious", "dangerous", "legit", "legitimate",
    "secure", "trustworthy", "malicious", "scam", "fraud", "phish",
    "compromised", "hacked", "reliable",
]

_BARE_URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)


def is_url_analysis_intent(text: str) -> bool:
    """
    True when the message should activate the URL Analyzer.

    Rules (strongest first):
      - A URL is present AND any analysis trigger/verb appears:
        "Analyze https://example.com", "Check https://example.com"
      - A URL is present AND a safety-verdict word appears — this catches
        question form: "Is https://example.com safe?", "Is it secure?",
        "Is this website malicious?"
      - A URL is present AND an analysis noun appears ("scan this url")
      - No URL but an explicit link-safety phrase is present ("check this
        url for phishing") — the user will be asked for the URL.
    """
    if not text:
        return False
    t = text.lower().strip()

    has_url = extract_url(t) is not None or bool(_BARE_URL_RE.search(t))
    has_trigger = any(k in t for k in _ANALYSIS_TRIGGERS)
    has_noun = any(k in t for k in _URL_NOUNS)
    has_safety_word = any(k in t for k in _SAFETY_QUESTION_WORDS)

    if has_url and (has_trigger or has_safety_word or has_noun):
        return True
    # No URL in the text, but a clear link-safety phrase → ask for the URL.
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
