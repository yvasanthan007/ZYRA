"""
nmap_service.py — Zyra Nmap Backend Service

Clean service layer linking the Nmap Scanner feature to the existing
nmap_scanner / nmap_handler modules.

Responsibilities:
  - Whitelisted scan operations (natural language → safe, validated operation)
  - Target validation (IP / CIDR / hostname)
  - Build the exact Nmap command string for display
  - Execute scans through the existing nmap_scanner engine
  - Parse results into structured, frontend-friendly data
  - Produce security observations (never calls an open port a vulnerability)
  - Cache last results for report generation / download

Safety model: the LLM / frontend never constructs arbitrary shell commands.
Only pre-defined operations in SCAN_OPERATIONS are allowed.
"""

import os
import sys
import re
import time
import uuid
import threading
from typing import Dict, Any, Optional, List, Tuple

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nmap_scanner import (
    NmapScanner,
    build_scan_args,
    get_nmap_version,
    analyze_scan_results,
)
from nmap_handler import (
    is_nmap_intent,
    extract_target_from_command,
)


# ──────────────────────────────────────────────
# Whitelisted scan operations
# ──────────────────────────────────────────────

SCAN_OPERATIONS = {
    "network_discovery": {
        "label": "Network Discovery",
        "scan_type": "ping_sweep",
        "description": "Discover active hosts on a network range (ping sweep)",
        "default_target": "192.168.1.0/24",
        "triggers": [
            "scan the network", "scan my network", "scan network",
            "network scan", "scan local network", "scan the local network",
            "scan the whole network", "network discovery",
        ],
    },
    "host_discovery": {
        "label": "Host Discovery",
        "scan_type": "ping_sweep",
        "description": "Find active hosts / devices on the network",
        "default_target": "192.168.1.0/24",
        "triggers": [
            "find active hosts", "active hosts", "find devices",
            "discover hosts", "host discovery", "devices on my network",
            "find devices on my network", "which devices are online",
        ],
    },
    "port_scan": {
        "label": "Port Scan",
        "scan_type": "quick",
        "description": "Scan the most common ports on a target",
        "default_target": "127.0.0.1",
        "triggers": [
            "open ports", "port scan", "check ports", "scan ports",
            "check for open ports", "which ports are open",
        ],
    },
    "service_detection": {
        "label": "Service/Version Detection",
        "scan_type": "standard",
        "description": "Detect services and versions running on a target",
        "default_target": "127.0.0.1",
        "triggers": [
            "services running", "check the services", "what services",
            "service detection", "service/version", "versions", "running services",
        ],
    },
    "full_scan": {
        "label": "Full Scan",
        "scan_type": "full",
        "description": "Comprehensive scan: all ports, OS detection, NSE scripts",
        "default_target": "127.0.0.1",
        "triggers": [
            "full scan", "deep scan", "complete scan", "full network scan",
        ],
    },
    "stealth_scan": {
        "label": "Stealth Scan",
        "scan_type": "stealth",
        "description": "Slow SYN scan (less intrusive)",
        "default_target": "127.0.0.1",
        "triggers": [
            "stealth scan", "stealth", "slow scan", "quiet scan",
        ],
    },
    "vulnerability_scan": {
        "label": "Vulnerability Scan",
        "scan_type": "vuln",
        "description": "Run Nmap NSE vulnerability scripts",
        "default_target": "127.0.0.1",
        "triggers": [
            "vulnerability scan", "vulnerabilities", "vuln scan",
            "check for vulnerabilities", "security scan",
        ],
    },
}

# Map "scan_type" values used by nmap_scanner to stable human labels for the panel
SCAN_TYPE_LABELS = {
    "ping_sweep": "Network / Host Discovery",
    "quick": "Port Scan (Top 100)",
    "standard": "Service / Version Detection",
    "full": "Full Scan (All Ports + OS + Scripts)",
    "stealth": "Stealth Scan",
    "vuln": "Vulnerability Scan",
}


# ──────────────────────────────────────────────
# Small in-memory result cache for report generation
# ──────────────────────────────────────────────

_RESULTS_STORE: Dict[str, Dict[str, Any]] = {}
_RESULT_TTL = 1800  # seconds
_RESULTS_LOCK = threading.Lock()


def _store_result(payload: Dict[str, Any]) -> str:
    scan_id = uuid.uuid4().hex[:12]
    payload["scan_id"] = scan_id
    payload["_stored_at"] = time.time()
    with _RESULTS_LOCK:
        # Evict stale entries
        now = time.time()
        stale = [k for k, v in _RESULTS_STORE.items() if now - v.get("_stored_at", 0) > _RESULT_TTL]
        for k in stale:
            _RESULTS_STORE.pop(k, None)
        _RESULTS_STORE[scan_id] = payload
    return scan_id


def get_result(scan_id: str) -> Optional[Dict[str, Any]]:
    with _RESULTS_LOCK:
        return _RESULTS_STORE.get(scan_id)



# ──────────────────────────────────────────────
# Intent resolution & target validation
# ──────────────────────────────────────────────

_IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_CIDR_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$")
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$")
_RANGE_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}-\d{1,3}$")


def validate_target(target: str) -> Tuple[bool, str]:
    """
    Validate a scan target: IP, CIDR range, hyphen range, or hostname.

    Returns:
        (is_valid, message)
    """
    if not target or not target.strip():
        return False, "No target provided."
    t = target.strip()

    if _IP_RE.match(t) or _CIDR_RE.match(t) or _RANGE_RE.match(t):
        for octet in re.findall(r"\d{1,3}", t):
            if int(octet) > 255:
                return False, f"Invalid IPv4 octet: {octet} (max 255)."
        if "/" in t:
            bits = int(t.split("/")[1])
            if bits < 0 or bits > 32:
                return False, f"Invalid CIDR prefix: /{bits} (must be 0-32)."
        return True, "Valid target."

    if _HOSTNAME_RE.match(t) and "." in t:
        return True, "Valid hostname."

    return False, f"Invalid target: '{t}'. Use an IP address (192.168.1.1), CIDR range (192.168.1.0/24), or a hostname."


def resolve_operation(text: str) -> Tuple[str, Dict[str, Any]]:
    """
    Resolve a natural-language request to a whitelisted scan operation.

    Returns:
        (operation_key, operation_meta)
    """
    if not text:
        return "network_discovery", SCAN_OPERATIONS["network_discovery"]

    low = text.lower().strip()

    for op_key, meta in SCAN_OPERATIONS.items():
        for trigger in meta["triggers"]:
            if trigger in low:
                return op_key, meta

    if "vuln" in low or "vulnerab" in low:
        return "vulnerability_scan", SCAN_OPERATIONS["vulnerability_scan"]
    if "stealth" in low or "quiet" in low:
        return "stealth_scan", SCAN_OPERATIONS["stealth_scan"]
    if "full" in low or "deep" in low or "complete" in low:
        return "full_scan", SCAN_OPERATIONS["full_scan"]
    if "service" in low or "version" in low:
        return "service_detection", SCAN_OPERATIONS["service_detection"]
    if "port" in low:
        return "port_scan", SCAN_OPERATIONS["port_scan"]
    if "host" in low or "device" in low or "active" in low:
        return "host_discovery", SCAN_OPERATIONS["host_discovery"]
    if "network" in low or "scan" in low or "nmap" in low:
        return "network_discovery", SCAN_OPERATIONS["network_discovery"]

    return "network_discovery", SCAN_OPERATIONS["network_discovery"]


def extract_target(text: str) -> Optional[str]:
    """
    Extract a target from a natural-language request (IP/CIDR/hostname).
    Reuses the existing nmap_handler extraction logic.
    """
    return extract_target_from_command(text)


def build_nmap_command(
    operation_key: str,
    target: str,
    ports: Optional[str] = None,
) -> str:
    """
    Build the exact, displayable nmap command for an operation + target.
    Matches what nmap_scanner will actually execute.
    """
    meta = SCAN_OPERATIONS.get(operation_key, SCAN_OPERATIONS["network_discovery"])
    scan_type = meta["scan_type"]
    args = build_scan_args(scan_type, target, ports=ports)
    return "nmap " + " ".join(args)


# ──────────────────────────────────────────────
# Structured results & security observations
# ──────────────────────────────────────────────

def structure_hosts(scan_results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert raw parsed nmap hosts into a clean, frontend-friendly structure.
    """
    hosts = []
    for h in scan_results.get("hosts", []):
        hosts.append({
            "ip": h.get("ip", ""),
            "hostname": h.get("hostname", ""),
            "mac": h.get("mac", ""),
            "status": (h.get("status") or "up").upper(),
            "os": h.get("os_match", ""),
            "ports": [
                {
                    "port": p.get("port"),
                    "protocol": p.get("protocol", "tcp"),
                    "state": (p.get("state") or "open").upper(),
                    "service": p.get("service", ""),
                    "version": p.get("version", ""),
                }
                for p in h.get("ports", [])
            ],
        })
    return hosts


_ATTENTION_SERVICES = {"ssh", "telnet", "ftp", "smtp", "smb", "rdp", "mysql",
                       "mssql", "mongodb", "redis", "vnc", "netbios-ssn",
                       "microsoft-ds", "ms-wbt-server"}


def build_security_observations(
    hosts: List[Dict[str, Any]],
    analysis: Dict[str, Any],
) -> List[str]:
    """
    Produce a conservative security summary.

    Wording follows the project convention:
      - "Service detected" / "Open port detected"
      - "Potential security observation" / "Further investigation recommended"
    Open ports are never automatically labelled as vulnerabilities.
    """
    obs: List[str] = []
    total_hosts = len(hosts)
    total_ports = sum(len(h.get("ports", [])) for h in hosts)

    obs.append(
        f"{total_hosts} active host(s) were discovered."
        if total_hosts != 1 else "1 active host was discovered."
    )
    if total_ports:
        obs.append(f"{total_ports} open port(s) were detected.")
    else:
        obs.append("No open ports were detected on the scanned targets.")

    web_hosts = 0
    service_counts: Dict[str, int] = {}
    for h in hosts:
        for p in h.get("ports", []):
            svc = (p.get("service") or "").lower().strip()
            if svc in ("http", "https", "www"):
                web_hosts += 1
            if svc:
                service_counts[svc] = service_counts.get(svc, 0) + 1

    if web_hosts:
        obs.append(f"{web_hosts} host(s) expose web service(s) (HTTP/HTTPS).")

    for svc, cnt in sorted(service_counts.items()):
        if svc in _ATTENTION_SERVICES:
            label = svc.upper()
            obs.append(
                f"{label} service detected ({cnt} instance(s)) — potential security "
                "observation, further investigation recommended."
            )

    real_vulns = 0
    for host_finding in analysis.get("findings", []):
        for item in host_finding.get("findings", []):
            if item.get("type") in ("vulnerable_version", "script_vuln"):
                real_vulns += 1
    if real_vulns:
        obs.append(
            f"{real_vulns} known issue(s) flagged by the built-in detection "
            "mechanism (outdated versions / NSE script results)."
        )

    verdict = analysis.get("verdict", "Unknown")
    obs.append(
        f"Overall assessment: {verdict} based on detected open ports and services. "
        "This is informational; open ports are not automatically vulnerabilities."
    )
    if analysis.get("recommendations"):
        obs.append("Recommendations: " + " ".join(analysis["recommendations"]))

    return obs


# ──────────────────────────────────────────────
# Scan execution
# ──────────────────────────────────────────────

def nmap_available() -> Dict[str, Any]:
    """Check whether Nmap is installed and reachable."""
    try:
        NmapScanner()
        return {"available": True, "version": get_nmap_version()}
    except Exception as e:
        return {"available": False, "version": "unknown", "error": str(e)}


def run_scan(
    operation_key: str,
    target: str,
    ports: Optional[str] = None,
    *,
    request_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a whitelisted scan operation on a validated target.

    Uses the existing nmap_scanner engine and caches the structured result so
    the dashboard can later generate/download a report.

    Returns:
        A dict describing the outcome (success/error plus structured data).
    """
    op = SCAN_OPERATIONS.get(operation_key)
    if op is None:
        return {"success": False, "error": f"Unknown operation: {operation_key}"}

    valid, msg = validate_target(target)
    if not valid:
        return {
            "success": False,
            "error": msg,
            "operation": operation_key,
            "operation_label": op["label"],
            "target": target,
            "command": build_nmap_command(operation_key, target, ports),
        }

    command = build_nmap_command(operation_key, target, ports)
    scan_type = op.get("scan_type", "ping_sweep")

    try:
        scanner = NmapScanner()
    except Exception as e:
        return {
            "success": False,
            "error": f"Nmap is not installed or cannot be located. {e}",
            "operation": operation_key,
            "operation_label": op["label"],
            "target": target,
            "command": command,
            "nmap_available": False,
        }

    try:
        if scan_type == "ping_sweep":
            raw = scanner.ping_sweep(target)
        else:
            raw = scanner.scan_host(target, scan_type=scan_type, ports=ports)
    except Exception as e:
        return {
            "success": False,
            "error": f"Scan execution error: {e}",
            "operation": operation_key,
            "operation_label": op["label"],
            "target": target,
            "command": command,
            "nmap_available": True,
        }

    if not raw.get("success"):
        return {
            "success": False,
            "error": raw.get("error", "Scan failed."),
            "operation": operation_key,
            "operation_label": op["label"],
            "target": target,
            "command": command,
            "nmap_available": True,
        }

    analysis = analyze_scan_results(raw)
    hosts = structure_hosts(raw)
    observations = build_security_observations(hosts, analysis)
    total_ports = sum(len(h.get("ports", [])) for h in hosts)

    payload = {
        "success": True,
        "status": "COMPLETE",
        "operation": operation_key,
        "operation_label": op["label"],
        "operation_description": op["description"],
        "scan_type": scan_type,
        "scan_type_label": SCAN_TYPE_LABELS.get(scan_type, op["label"]),
        "target": target,
        "command": command,
        "timestamp": raw.get("timestamp"),
        "nmap_version": get_nmap_version(),
        "hosts": hosts,
        "hosts_count": len(hosts),
        "open_ports_count": total_ports,
        "analysis": {
            "verdict": analysis.get("verdict", "Unknown"),
            "score": analysis.get("total_score", 0),
            "recommendations": analysis.get("recommendations", []),
        },
        "observations": observations,
        "summary": (
            f"Network scan completed. I discovered {len(hosts)} active host(s) and "
            f"{total_ports} open port(s). The detailed results are available in the "
            f"Nmap Scanner panel."
        ),
        "request_text": request_text or "",
    }

    _store_result(payload)
    return payload
