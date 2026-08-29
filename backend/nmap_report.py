"""
nmap_report.py — Zyra Nmap Report Generator

Produces structured machine-readable reports (JSON), human-readable reports
(PDF + plain text) from the structured scan payload produced by nmap_service.

The PDF generator is intentionally dependency-free: it writes a minimal,
valid single/multi-page PDF using only the Python standard library.
"""

import os
import sys
import io
import json
from datetime import datetime
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ──────────────────────────────────────────────
# Report data assembly
# ──────────────────────────────────────────────

def build_report_data(scan_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the complete report structure from a scan payload."""
    analysis = scan_payload.get("analysis", {})
    return {
        "title": "ZYRA - Network Security Scan Report",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "scan": {
            "target": scan_payload.get("target", ""),
            "timestamp": scan_payload.get("timestamp", ""),
            "operation": scan_payload.get("operation_label", ""),
            "operation_key": scan_payload.get("operation", ""),
            "scan_type": scan_payload.get("scan_type_label", ""),
            "command": scan_payload.get("command", ""),
            "status": scan_payload.get("status", "COMPLETE"),
            "nmap_version": scan_payload.get("nmap_version", ""),
        },
        "hosts": scan_payload.get("hosts", []),
        "security": {
            "active_hosts": scan_payload.get("hosts_count", 0),
            "open_ports": scan_payload.get("open_ports_count", 0),
            "observations": scan_payload.get("observations", []),
            "verdict": analysis.get("verdict", "Unknown"),
            "score": analysis.get("score", 0),
            "recommendations": analysis.get("recommendations", []),
        },
    }


def report_to_json(report_data: Dict[str, Any]) -> str:
    """Serialize report data to a JSON string."""
    return json.dumps(report_data, indent=2, ensure_ascii=False)


# ──────────────────────────────────────────────
# Plain text (human-readable, chat/console friendly)
# ──────────────────────────────────────────────

def _ascii(s) -> str:
    if s is None:
        return ""
    return (str(s)
            .replace("\u2022", "-")
            .replace("\u2192", "->")
            .replace("\u2014", "--")
            .replace("\u2013", "-")
            .replace("\u2714", "[OK]")
            .replace("\u26a0", "[!]")
    )


def report_to_text(report_data: Dict[str, Any]) -> str:
    """Build a human-readable text report."""
    scan = report_data.get("scan", {})
    sec = report_data.get("security", {})

    lines: List[str] = []
    lines.append("=" * 60)
    lines.append(report_data.get("title", ""))
    lines.append("=" * 60)
    lines.append("")
    lines.append("Scan Information")
    lines.append("-" * 40)
    lines.append(f"  Target:        {scan.get('target', '-')}")
    lines.append(f"  Operation:     {scan.get('operation', '-')}")
    lines.append(f"  Scan type:     {scan.get('scan_type', '-')}")
    lines.append(f"  Timestamp:     {scan.get('timestamp', '-')}")
    lines.append(f"  Status:        {scan.get('status', '-')}")
    lines.append(f"  Nmap version:  {scan.get('nmap_version', '-')}")
    lines.append(f"  Command:       {scan.get('command', '-')}")
    lines.append("")

    lines.append("Host Information")
    lines.append("-" * 40)
    hosts = report_data.get("hosts", [])
    if not hosts:
        lines.append("  No active hosts were returned by the scan.")
    for h in hosts:
        ip = h.get("ip", "-")
        hn = h.get("hostname", "") or "-"
        mac = h.get("mac", "") or "-"
        osinfo = h.get("os", "") or "-"
        lines.append(f"  {ip}  ({hn})")
        lines.append(f"      Status: {h.get('status', '-')}  |  MAC: {mac}  |  OS: {osinfo}")
        ports = h.get("ports", [])
        if ports:
            for p in ports:
                svc = p.get("service", "") or "unknown"
                ver = p.get("version", "") or ""
                lines.append(
                    f"      Port: {p.get('port')}/{p.get('protocol')}  {p.get('state', '-')}  -> {svc}  {ver}"
                )
        else:
            lines.append("      Ports: none detected")
    lines.append("")

    lines.append("Security Summary")
    lines.append("-" * 40)
    lines.append(f"  Active hosts:      {sec.get('active_hosts', 0)}")
    lines.append(f"  Open ports:        {sec.get('open_ports', 0)}")
    lines.append(f"  Overall assessment: {sec.get('verdict', 'Unknown')} (score {sec.get('score', 0)})")
    obs = sec.get("observations", [])
    if obs:
        lines.append("  Security observations:")
        for o in obs:
            lines.append(f"    - {_ascii(o)}")
    recs = sec.get("recommendations", [])
    if recs:
        lines.append("  Recommendations:")
        for r in recs:
            lines.append(f"    - {_ascii(r)}")
    lines.append("")
    lines.append("Generated by ZYRA Network Security Scanner")
    lines.append("=" * 60)
    return "\n".join(lines)

# ──────────────────────────────────────────────
# Minimal dependency-free PDF generator
# ──────────────────────────────────────────────

def _pdf_escape(text: str) -> str:
    return _ascii(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: str, width: int = 96) -> List[str]:
    text = str(text)
    if len(text) <= width:
        return [text]
    words = text.split(" ")
    lines: List[str] = []
    cur = ""
    for word in words:
        if len(cur) + len(word) + 1 > width:
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    if cur:
        lines.append(cur)
    return lines


def report_to_pdf(report_data: Dict[str, Any]) -> bytes:
    """
    Generate a minimal, human-readable PDF (no external dependencies).

    Lays out the text report with page breaks and returns raw PDF bytes.
    """
    text_report = report_to_text(report_data)
    raw_lines = text_report.split("\n")
    wrapped: List[str] = []
    for raw in raw_lines:
        wrapped.extend(_wrap(raw))
    pages = [wrapped[i:i + 52] for i in range(0, len(wrapped), 52)]

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

