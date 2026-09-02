"""
backend/dns_lookup/__init__.py — ZYRA DNS Lookup Package

A real DNS intelligence engine for the ZYRA dashboard, backed by dnspython.

Modules:
    validator   — domain/IP validation, sanitization and internal-host blocking
    resolver    — real DNS record queries via dnspython (A, AAAA, CNAME, MX,
                  NS, TXT/SPF/DMARC, SOA, PTR, DNSSEC) — no shell commands
    analyzer    — lookup pipeline orchestrator + scan registry
    intent      — DNS_LOOKUP intent detection for chat / voice
    report      — structured report + dependency-free PDF

The frontend never performs DNS analysis itself: every query runs here, in
the backend, with timeouts and full error handling.
"""

from backend.dns_lookup.analyzer import (  # noqa: F401
    DNS_STAGES,
    STAGE_PROGRESS,
    build_voice_summary,
    get_dns_lookup,
    get_last_dns_lookup,
    get_scan_state,
    run_dns_lookup,
    start_dns_lookup,
)
from backend.dns_lookup.history import (  # noqa: F401
    add_entry as dns_history_add,
    find as dns_history_find,
    recent as dns_history_recent,
)
from backend.dns_lookup.intent import (  # noqa: F401
    build_chat_ack,
    extract_dns_record_type,
    extract_dns_target,
    is_dns_intent,
)
from backend.dns_lookup.report import (  # noqa: F401
    build_report_data as build_dns_report_data,
    dns_report_filename,
    report_to_pdf as dns_report_to_pdf,
    report_to_text as dns_report_to_text,
)
from backend.dns_lookup.resolver import (  # noqa: F401
    get_dns_server_info,
    query_single,
    resolve_all,
)
from backend.dns_lookup.validator import (  # noqa: F401
    DomainValidationError,
    validate_domain,
)

__all__ = [
    "DNS_STAGES",
    "STAGE_PROGRESS",
    "DomainValidationError",
    "build_chat_ack",
    "build_dns_report_data",
    "build_voice_summary",
    "dns_history_add",
    "dns_history_find",
    "dns_history_recent",
    "dns_report_filename",
    "dns_report_to_pdf",
    "dns_report_to_text",
    "extract_dns_record_type",
    "extract_dns_target",
    "get_dns_lookup",
    "get_dns_server_info",
    "get_last_dns_lookup",
    "get_scan_state",
    "is_dns_intent",
    "query_single",
    "resolve_all",
    "run_dns_lookup",
    "start_dns_lookup",
    "validate_domain",
]
