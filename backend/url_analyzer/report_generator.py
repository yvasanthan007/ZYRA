"""
backend/url_analyzer/report_generator.py — URL analysis report + PDF

Builds the full "ZYRA URL SECURITY ANALYSIS REPORT" (text + PDF) from a
completed scan result. The PDF generator reuses ZYRA's existing
dependency-free PDF infrastructure from backend/nmap_report.py so no new
dependencies are introduced.

Filename convention:
    ZYRA_URL_Analysis_<domain>_<timestamp>.pdf
    e.g. ZYRA_URL_Analysis_example.com_2026-08-29_201530.pdf
"""

import os
import sys
from datetime import datetime
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.nmap_report import _pdf_escape, _wrap  # existing PDF infra

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def build_report_data(result: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the complete report structure from a scan result payload."""
    url_details = result.get("url_details", {})
    ssl = result.get("ssl", {}) or {}
    domain = result.get("domain", {}) or {}
    reputation = result.get("reputation", {}) or {}
    findings = result.get("findings", []) or []

    return {
        "title": "ZYRA URL SECURITY ANALYSIS REPORT",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "scan": {
            "scan_id": result.get("scan_id", ""),
            "timestamp": result.get("timestamp", ""),
            "target_url": result.get("url", ""),
        },
        "final": {
            "safety_score": result.get("score", 0),
            "risk_level": result.get("risk_level_label", ""),
            "classification": result.get("classification_label", ""),
            "classification_summary": result.get("classification_summary", ""),
        },
        "url_information": {
            "protocol": url_details.get("protocol", ""),
            "domain": url_details.get("domain", ""),
            "ip": url_details.get("ip_address") or "unresolved",
            "port": url_details.get("port", ""),
            "path": url_details.get("path", ""),
            "redirects": url_details.get("redirects", 0),
        },
        "ssl": {
            "status": (ssl.get("status") or "").upper() or "UNKNOWN",
            "issuer": ssl.get("issuer") or "n/a",
            "expires": ssl.get("expires") or "n/a",
            "tls": ssl.get("tls_version") or "n/a",
            "error": ssl.get("error"),
        },
        "domain": {
            "registered_domain": domain.get("registered_domain", ""),
            "subdomain_count": domain.get("subdomain_count", 0),
            "dns": ("Resolved — " + ", ".join((domain.get("ips") or [])[:3]))
                    if domain.get("resolved") else "Could not be resolved",
            "whois": "Available" if domain.get("whois_available")
                     else "Information unavailable",
            "hosting": domain.get("hosting_asn") or "Information unavailable",
        },
        "threat_intelligence": {
            "provider": reputation.get("provider") or "Not configured",
            "reputation": reputation.get("reputation", "Unknown"),
            "malware": reputation.get("malware", "Unknown"),
            "phishing": reputation.get("phishing", "Unknown"),
            "note": reputation.get("note"),
        },
        "findings": sorted(
            findings,
            key=lambda f: SEVERITY_ORDER.get(f.get("severity", "INFO"), 9),
        ),
        "recommendation": result.get("recommendation", ""),
        "score_reasoning": result.get("reasoning", []) or [],
    }


def report_to_text(report_data: Dict[str, Any]) -> str:
    """Build the human-readable text report (also feeds the PDF layout)."""
    L: List[str] = []
    L.append("=" * 64)
    L.append(report_data.get("title", "ZYRA URL SECURITY ANALYSIS REPORT"))
    L.append("=" * 64)
    L.append("")

    scan = report_data.get("scan", {})
    L.append("Scan Information")
    L.append("-" * 40)
    L.append(f"  Scan ID:        {scan.get('scan_id', '-')}")
    L.append(f"  Timestamp:      {scan.get('timestamp', '-')}")
    L.append(f"  Target URL:     {scan.get('target_url', '-')}")
    L.append("")

    final = report_data.get("final", {})
    L.append("FINAL RESULT")
    L.append("-" * 40)
    L.append(f"  Safety Score:   {final.get('safety_score', 0)} / 100")
    L.append(f"  Risk Level:     {final.get('risk_level', '-')}")
    L.append(f"  Classification: {final.get('classification', '-')}")

    ssl = report_data.get("ssl", {})
    L.append("SSL/TLS ANALYSIS")
    L.append("-" * 40)
    L.append(f"  Certificate:    {ssl.get('status', '-')}")
    L.append(f"  Issuer:         {ssl.get('issuer', '-')}")
    L.append(f"  Expiration:     {ssl.get('expires', '-')}")
    L.append(f"  TLS:            {ssl.get('tls', '-')}")
    if ssl.get("error"):
        L.append(f"  Note:           {ssl['error']}")
    L.append("")

    dom = report_data.get("domain", {})
    L.append("DOMAIN ANALYSIS")
    L.append("-" * 40)
    L.append(f"  Domain:         {dom.get('registered_domain', '-')}")
    L.append(f"  DNS:            {dom.get('dns', '-')}")
    L.append(f"  WHOIS:          {dom.get('whois', '-')}")
    L.append(f"  Hosting:        {dom.get('hosting', '-')}")
    L.append("")

    ti = report_data.get("threat_intelligence", {})
    L.append("THREAT INTELLIGENCE")
    L.append("-" * 40)
    L.append(f"  Provider:       {ti.get('provider', '-')}")
    L.append(f"  Reputation:     {ti.get('reputation', '-')}")
    L.append(f"  Malware:        {ti.get('malware', '-')}")
    L.append(f"  Phishing:       {ti.get('phishing', '-')}")
    if ti.get("note"):
        L.append(f"  Note:           {ti['note']}")
    L.append("")

    L.append("SECURITY FINDINGS")
    L.append("-" * 40)
    findings = report_data.get("findings", [])
    if not findings:
        L.append("  No suspicious indicators were detected during this scan.")
    for f in findings:
        L.append(f"  [{f.get('severity', 'INFO')}] {f.get('title', '')}")
        detail = f.get("detail", "")
        if detail:
            for wline in _wrap(detail, width=58):
                L.append(f"        {wline}")
    L.append("")

    reasoning = report_data.get("score_reasoning", [])
    if reasoning:
        L.append("SCORE BREAKDOWN")
        L.append("-" * 40)
        for r in reasoning:
            for wline in _wrap(r, width=58):
                L.append(f"  {wline}")
        L.append("")

    L.append("RECOMMENDATION")
    L.append("-" * 40)
    for wline in _wrap(report_data.get("recommendation", "-"), width=58):
        L.append(f"  {wline}")
    L.append("")

    L.append("-" * 64)
    L.append("Generated by: ZYRA // NEURAL CORE")
    L.append(f"Timestamp: {report_data.get('generated', '-')}")
    L.append("=" * 64)
    return "\n".join(L)


# ──────────────────────────────────────────────
# PDF generation (reuses ZYRA's dependency-free PDF engine)
# ──────────────────────────────────────────────

def report_to_pdf(report_data: Dict[str, Any]) -> bytes:
    """
    Generate a professional multi-page PDF from the text report.
    Same minimal, valid PDF writer used by the Nmap report generator.
    """
    import io

    text_report = report_to_text(report_data)
    raw_lines = text_report.split("\n")
    wrapped: List[str] = []
    for raw in raw_lines:
        wrapped.extend(_wrap(raw, width=96))
    pages = [wrapped[i:i + 52] for i in range(0, len(wrapped), 52)]
    if not pages:
        pages = [["(empty report)"]]

    catalog_id = 1
    pages_id = 2
    count = len(pages)
    page_ids = list(range(3, 3 + count))
    stream_ids = list(range(3 + count, 3 + 2 * count))
    font_id = 3 + 2 * count

    objs: Dict[int, str] = {}
    objs[catalog_id] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>"
    kid_list = " ".join(f"{pid} 0 R" for pid in page_ids)
    objs[pages_id] = f"<< /Type /Pages /Kids [{kid_list}] /Count {count} >>"

    for i, pid in enumerate(page_ids):
        objs[pid] = (
            f"<< /Type /Page /Parent {pages_id} 0 R "
            "/MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {stream_ids[i]} 0 R >>"
        )

    for i, sid in enumerate(stream_ids):
        content = ["BT", "/F1 9 Tf", "40 800 Td", "13 TL"]
        for line in pages[i]:
            content.append(f"({_pdf_escape(line)}) Tj")
            content.append("T*")
        content.append("ET")
        stream = "\n".join(content)
        objs[sid] = (
            f"<< /Length {len(stream.encode('latin-1', 'replace'))} >>\n"
            f"stream\n{stream}\nendstream"
        )

    objs[font_id] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: Dict[int, int] = {}
    for oid in range(1, font_id + 1):
        offsets[oid] = out.tell()
        out.write(f"{oid} 0 obj\n{objs[oid]}\nendobj\n".encode("latin-1", "replace"))

    xref_pos = out.tell()
    total_objs = font_id + 1
    out.write(f"xref\n0 {total_objs}\n".encode("latin-1"))
    out.write(b"0000000000 65535 f \n")
    for oid in range(1, total_objs):
        out.write(f"{offsets[oid]:010d} 00000 n \n".encode("latin-1"))
    out.write(
        (f"trailer\n<< /Size {total_objs} /Root {catalog_id} 0 R >>\n"
         "startxref\n"
         f"{xref_pos}\n"
         "%%EOF\n").encode("latin-1")
    )
    return out.getvalue()


def report_filename(result: Dict[str, Any]) -> str:
    """ZYRA_URL_Analysis_<domain>_<timestamp>.pdf"""
    domain = (result.get("domain_display")
              or result.get("hostname")
              or "scan")
    domain = "".join(c for c in str(domain) if c.isalnum() or c in ".-") or "scan"
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"ZYRA_URL_Analysis_{domain}_{stamp}.pdf"

    L.append("")

    ui = report_data.get("url_information", {})
    L.append("URL INFORMATION")
    L.append("-" * 40)
    L.append(f"  Protocol:       {ui.get('protocol', '-')}")
    L.append(f"  Domain:         {ui.get('domain', '-')}")
    L.append(f"  IP:             {ui.get('ip', '-')}")
    L.append(f"  Port:           {ui.get('port', '-')}")
    L.append(f"  Path:           {ui.get('path', '-')}")
    L.append(f"  Redirects:      {ui.get('redirects', 0)}")
    L.append("")
    return "\n".join(L)
