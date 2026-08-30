"""
backend/dns_lookup/__init__.py — ZYRA DNS Lookup Package

A real DNS intelligence engine for the ZYRA dashboard, backed by dnspython.

Modules:
    validator   — domain/IP validation, sanitization and internal-host blocking
    resolver    — real DNS record queries via dnspython (A, AAAA, CNAME, MX,
                  NS, TXT/SPF/DMARC, SOA, PTR, DNSSEC) — no shell commands
    scorer      — transparent DNS security scoring (0-100) from actual results
    analyzer    — lookup pipeline orchestrator + scan registry
    intent      — DNS_LOOKUP intent detection for chat / voice
    report      — structured report + dependency-free PDF

The frontend never performs DNS analysis itself: every query runs here, in
the backend, with timeouts and full error handling.
"""

from backend.dns_lookup.analyzer import (  # noqa: F401
    DNS_STAGES,
    build_voice_summary,
    get_scan_state,
    get_last_scan,
    run_dns_lookup,
)
from backend.dns_lookup.intent import (  # noqa: F401
    build_chat_ack,
    extract_dns_target,
    is_dns_intent,
)
from backend.dns_lookup.report import (  # noqa: F401
    build_report_data as build_dns_report_data,
    dns_report_filename,
    report_to_pdf as dns_report_to_pdf,
    report_to_text as dns_report_to_text,
)

__all__ = [
    "DNS_STAGES",
    "build_chat_ack",
    "build_dns_report_data",
    "build_voice_summary",
    "dns_report_filename",
    "dns_report_to_pdf",
    "dns_report_to_text",
    "extract_dns_target",
    "get_last_scan",
    "get_scan_state",
    "is_dns_intent",
    "run_dns_lookup",
]
