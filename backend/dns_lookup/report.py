"""
backend/dns_lookup/report.py — DNS lookup report + PDF

Builds the full "ZYRA DNS SECURITY LOOKUP REPORT" (text + PDF) from a
completed lookup result. The PDF generator reuses ZYRA's existing
dependency-free PDF infrastructure from backend/nmap_report.py so no new
dependencies are introduced.

Filename convention:
    ZYRA_DNS_Lookup_<domain>_<timestamp>.pdf
    e.g. ZYRA_DNS_Lookup_example.com_2026-08-31_201530.pdf
"""

import os
import sys
from datetime import datetime
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.nmap_report import _pdf_escape, _wrap  # existing PDF infra

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def build_report_data(result: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the complete report structure from a lookup result payload."""
    records = result.get("records", {}) or {}
    txt_policy = result.get("txt_policy", {}) or {}
    dnssec = result.get("dnssec", {}) or {}
    resolution = result.get("resolution", {}) or {}
    reverse = result.get("reverse", {}) or {}
    findings = result.get("findings", []) or []

    return {
        "title": "ZYRA DNS SECURITY LOOKUP REPORT",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "lookup": {
            "lookup_id": result.get("lookup_id", ""),
            "timestamp": result.get("timestamp", ""),
            "domain": result.get("domain_display") or result.get("domain", ""),
            "apex": result.get("apex", ""),
            "source": result.get("source", ""),
            "lookup_status": result.get("status", ""),
        },
        "final": {
            "security_score": result.get("score", 0),
            "risk_level": result.get("risk_level_label", ""),
            "resolution_status": result.get("status", ""),
        },
        "performance": {
            "response_time_ms": result.get("response_time_ms"),
            "total_time_ms": result.get("total_time_ms"),
        },
        "resolution": {
            "resolved": bool(resolution.get("resolved")),
            "addresses": ", ".join((resolution.get("ips") or [])[:8]) or "none",
            "error": resolution.get("error"),
        },
        "dns_records": {
            "a": _fmt_records(records.get("A")),
            "aaaa": _fmt_records(records.get("AAAA")),
            "cname": _fmt_records(records.get("CNAME")),
            "mx": _fmt_records(records.get("MX")),
            "ns": _fmt_records(records.get("NS")),
            "txt": _fmt_records(records.get("TXT")),
            "soa": _fmt_records(records.get("SOA")),
        },
        "mail_policy": {
            "spf_present": (txt_policy.get("spf", {}) or {}).get("present", False),
            "spf_record": (txt_policy.get("spf", {}) or {}).get("record") or "not present",
            "spf_all_policy": (txt_policy.get("spf", {}) or {}).get("all_policy") or "n/a",
            "dmarc_present": (txt_policy.get("dmarc", {}) or {}).get("present", False),
            "dmarc_record": (txt_policy.get("dmarc", {}) or {}).get("record") or "not present",
            "dmarc_policy": (txt_policy.get("dmarc", {}) or {}).get("policy") or "n/a",
        },
        "reverse_dns": {
            "queried_ips": ", ".join(reverse.get("queried_ips") or []) or "n/a",
            "hostnames": ", ".join(reverse.get("hostnames") or []) or "none found",
        },
        "dnssec": {
            "status": (dnssec.get("status") or "NOT_ENABLED"),
            "dnskey": dnssec.get("dnskey", False),
            "ds": dnssec.get("ds", False),
            "validated": dnssec.get("ad_flag", False),
            "detail": dnssec.get("detail", ""),
        },
        "warnings": result.get("warnings", []) or [],
        "findings": sorted(
            findings,
            key=lambda f: SEVERITY_ORDER.get(f.get("severity", "INFO"), 9),
        ),
        "recommendation": result.get("recommendation", "-"),
    }


def _fmt_records(block) -> str:
    """Format one record-type block for the report ('value [TTL s], ...')."""
    if not isinstance(block, dict) or block.get("status") != "OK":
        return "none" if not (block or {}).get("error") else f"none ({block.get('error')})"
    return ", ".join(
        f"{r.get('value')} [TTL {r.get('ttl')}s]" for r in block.get("records", [])
    ) or "none"

# ──────────────────────────────────────────────
# Plain text (human-readable, chat/console friendly)
# ──────────────────────────────────────────────

def report_to_text(report_data: Dict[str, Any]) -> str:
    """Build a human-readable text report."""
    lk = report_data.get("lookup", {})
    fin = report_data.get("final", {})
    perf = report_data.get("performance", {})
    res = report_data.get("resolution", {})
    rec = report_data.get("dns_records", {})
    mail = report_data.get("mail_policy", {})
    rev = report_data.get("reverse_dns", {})
    sec = report_data.get("dnssec", {})

    L: List[str] = []
    L.append("=" * 64)
    L.append(report_data.get("title", "ZYRA DNS SECURITY LOOKUP REPORT"))
    L.append("=" * 64)
    L.append("")
    L.append("LOOKUP INFORMATION")
    L.append("-" * 40)
    L.append(f"  Domain:          {lk.get('domain', '-')}")
    L.append(f"  Registered zone: {lk.get('apex', '-')}")
    L.append(f"  Lookup ID:       {lk.get('lookup_id', '-')}")
    L.append(f"  Timestamp:       {lk.get('timestamp', '-')}")
    L.append(f"  Lookup status:   {lk.get('lookup_status', '-')}")
    L.append(f"  Source:          {lk.get('source', '-')}")
    L.append("")
    L.append("RESULT SUMMARY")
    L.append("-" * 40)
    L.append(f"  Resolution:      {fin.get('resolution_status', '-')}")
    L.append(f"  Security score:  {fin.get('security_score', 0)} / 100")
    L.append(f"  Risk level:      {fin.get('risk_level', '-')}")
    L.append(f"  Response time:   {perf.get('response_time_ms', '-')} ms")
    L.append(f"  Total time:      {perf.get('total_time_ms', '-')} ms")
    L.append("")
    L.append("DNS RECORDS")
    L.append("-" * 40)
    L.append(f"  A (IPv4):     {rec.get('a', 'none')}")
    L.append(f"  AAAA (IPv6):  {rec.get('aaaa', 'none')}")
    L.append(f"  CNAME:        {rec.get('cname', 'none')}")
    L.append(f"  MX:           {rec.get('mx', 'none')}")
    L.append(f"  NS:           {rec.get('ns', 'none')}")
    L.append(f"  TXT:          {rec.get('txt', 'none')}")
    L.append(f"  SOA:          {rec.get('soa', 'none')}")
    L.append("")
    L.append("MAIL POLICY")
    L.append("-" * 40)
    L.append(f"  SPF:          {'present' if mail.get('spf_present') else 'NOT PRESENT'}")
    L.append(f"  SPF record:   {mail.get('spf_record', '-')}")
    L.append(f"  SPF all:      {mail.get('spf_all_policy', '-')}")
    L.append(f"  DMARC:        {'present' if mail.get('dmarc_present') else 'NOT PRESENT'}")
    L.append(f"  DMARC policy: {mail.get('dmarc_policy', '-')}")
    L.append("")
    L.append("REVERSE DNS (PTR)")
    L.append("-" * 40)
    L.append(f"  Queried IPs:  {rev.get('queried_ips', '-')}")
    L.append(f"  Hostnames:    {rev.get('hostnames', '-')}")
    L.append("")
    L.append("DNSSEC")
    L.append("-" * 40)
    L.append(f"  Status:       {sec.get('status', '-')}")
    L.append(f"  DNSKEY:       {'yes' if sec.get('dnskey') else 'no'}")
    L.append(f"  DS:           {'yes' if sec.get('ds') else 'no'}")
    L.append(f"  Validated:    {'yes' if sec.get('validated') else 'no'}")
    for wline in _wrap(str(sec.get("detail", "-")), width=58):
        L.append(f"  {wline}")
    L.append("")

    warnings = report_data.get("warnings", [])
    L.append("WARNINGS")
    L.append("-" * 40)
    if warnings:
        for w in warnings:
            for wline in _wrap(f"- {w}", width=58):
                L.append(f"  {wline}")
    else:
        L.append("  No warnings.")
    L.append("")

    L.append("FINDINGS")
    L.append("-" * 40)
    findings = report_data.get("findings", [])
    if findings:
        for f in findings:
            L.append(f"  [{f.get('severity', 'INFO')}] {f.get('title', '')}")
            for wline in _wrap(str(f.get('detail', '')), width=56):
                L.append(f"      {wline}")
    else:
        L.append("  No security findings — DNS posture looks clean.")
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
    Same minimal, valid PDF writer used by the Nmap/URL report generators.
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


def dns_report_filename(result: Dict[str, Any]) -> str:
    """ZYRA_DNS_Lookup_<domain>_<timestamp>"""
    domain = (result.get("domain_display")
              or result.get("domain")
              or "lookup")
    domain = "".join(c for c in str(domain) if c.isalnum() or c in ".-") or "lookup"
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"ZYRA_DNS_Lookup_{domain}_{stamp}"
