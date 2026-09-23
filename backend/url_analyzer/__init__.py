"""
backend/url_analyzer/__init__.py — ZYRA URL Analyzer Package

A production URL security-analysis engine for the ZYRA dashboard.

Modules:
    validator        — URL validation, normalization and SSRF protections
    dns_analyzer     — DNS resolution and domain parsing
    ssl_analyzer     — SSL/TLS certificate analysis
    reputation       — pluggable threat-intelligence providers (env-configured)
    threat_detector  — URL structure threat heuristics
    risk_scorer      — transparent risk scoring (0-100 safety score)
    analyzer         — scan pipeline orchestrator + scan registry
    report_generator — structured report + dependency-free PDF
    history          — recent scan history persistence

The frontend never performs security analysis itself and never sees API
keys: every check runs here, in the backend.
"""

from backend.url_analyzer.analyzer import (  # noqa: F401
    SCAN_STAGES,
    STAGE_PROGRESS,
    build_voice_summary,
    get_history,
    get_last_scan,
    get_scan,
    get_scan_state,
    run_url_scan,
    start_scan,
)
from backend.url_analyzer.intent import (  # noqa: F401
    build_chat_ack,
    extract_target_url,
    is_url_analysis_intent,
)
from backend.url_analyzer.report_generator import (  # noqa: F401
    build_report_data,
    report_filename,
    report_to_pdf,
    report_to_text,
)

__all__ = [
    "SCAN_STAGES",
    "STAGE_PROGRESS",
    "build_chat_ack",
    "build_report_data",
    "build_voice_summary",
    "extract_target_url",
    "get_history",
    "get_last_scan",
    "get_scan",
    "get_scan_state",
    "is_url_analysis_intent",
    "report_filename",
    "report_to_pdf",
    "report_to_text",
    "run_url_scan",
    "start_scan",
]
