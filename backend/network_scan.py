"""
backend/network_scan.py — ZYRA "Scan My Network" (real-time local subnet scan)

One shared network-scan function used by BOTH typed chat and voice chat:

    user says/types "Scan my network"
      -> intent detected here
      -> active local private IPv4 detected programmatically (never hardcoded,
         never the public IP)
      -> local /24 subnet derived from that interface
      -> subnet validated as private/local
      -> nmap -sn <subnet> host discovery run through the EXISTING
         NmapScanner engine (argument-list execution, no shell construction)
      -> output parsed into structured device info
      -> results returned as a normal ZYRA chat response

Errors (Nmap missing, no network, scan failure) are returned as chat text so
they surface inside the existing ZYRA chat — no terminal, popup or new page.
"""

import ipaddress
import re
import socket
import sys
import os
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Intent detection (chat + voice transcripts) ─────────────────────────

_NETWORK_SCAN_TRIGGERS = [
    "scan my network",
    "scan the network",
    "scan my local network",
    "scan the local network",
    "scan network",
    "network scan",
    "show devices on my network",
    "show devices on the network",
    "discover devices on my network",
    "discover devices on the network",
    "devices on my network",
    "find devices on my network",
    "what devices are on my network",
    "discover hosts on my network",
    "show devices on my wifi",
    "scan my wifi network",
]

# An explicit target (IP/CIDR) means the user wants the generic Nmap scanner
# on that specific host/range — that must NOT be hijacked by the local scan.
_EXPLICIT_TARGET_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b")


def _normalize(text: str) -> str:
    """Lowercase and collapse spacing for robust phrase matching."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip(" .!?,:")


def is_network_scan_intent(text: str) -> bool:
    """
    True when the user asks for a real-time scan of THEIR local network
    (typed or spoken) without naming an explicit target IP/CIDR.
    """
    if not text:
        return False
    normalized = _normalize(text)
    if not normalized:
        return False
    if _EXPLICIT_TARGET_RE.search(normalized):
        return False
    return any(trigger in normalized for trigger in _NETWORK_SCAN_TRIGGERS)


# ── Local interface / subnet detection ──────────────────────────────────

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def _is_private_ipv4(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.version == 4 and any(addr in net for net in _PRIVATE_NETS)


def detect_local_ipv4() -> Optional[str]:
    """
    Detect the active local interface's private IPv4 address.

    Primary: connect a UDP socket to a public address (no packet is sent —
    UDP connect only picks the default route's source address), so the
    address reflects the interface actually used. Fallback: hostname lookup.
    """
    candidate = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(1.0)
            s.connect(("8.8.8.8", 80))
            candidate = s.getsockname()[0]
        finally:
            s.close()
    except Exception:  # noqa: BLE001 — an offline machine still has a local IP
        candidate = None

    if candidate and _is_private_ipv4(candidate) and not candidate.startswith("127."):
        return candidate

    try:
        host_ip = socket.gethostbyname(socket.gethostname())
        if _is_private_ipv4(host_ip) and not host_ip.startswith("127."):
            return host_ip
    except Exception:  # noqa: BLE001
        pass
    return None


def detect_local_subnet() -> Tuple[Optional[str], Optional[str]]:
    """
    Return (local_ip, subnet_cidr) for the active local interface,
    e.g. ("192.168.1.10", "192.168.1.0/24"), or (None, None).
    """
    local_ip = detect_local_ipv4()
    if not local_ip:
        return None, None
    try:
        # Derive the /24 network from the interface address (never hardcoded).
        network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
        return local_ip, str(network)
    except ValueError:
        return local_ip, None


# ── Shared scan function ────────────────────────────────────────────────

_MAC_RE = re.compile(
    r"(?:MAC [Aa]ddress|MAC):\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})"
    r"(?:\s+\(([^)]+)\))?"
)


def _parse_ping_sweep_output(stdout: str) -> List[Dict[str, Any]]:
    """
    Parse `nmap -sn` text output into structured device records:
    [{ip, hostname, mac, vendor}]. Uses the same "Nmap scan report for"
    anchors as the existing nmap_scanner parser, plus the MAC/vendor lines
    that only appear in raw -sn output.
    """
    devices: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    ip_re = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")

    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if line.startswith("Nmap scan report for"):
            if current:
                devices.append(current)
            tail = line.split("for", 1)[-1].strip()
            m = ip_re.search(tail)
            if not m:
                current = None  # not an IPv4 host report (e.g. IPv6) — skip
                continue
            ip = m.group(1)
            # Format: "HOSTNAME (192.168.1.5)" or just "192.168.1.5".
            # The hostname (when present) sits BEFORE the parentheses.
            hostname = tail.split("(", 1)[0].strip() if "(" in tail else ""
            if hostname == ip:
                hostname = ""
            current = {
                "ip": ip,
                "hostname": hostname,
                "mac": "",
                "vendor": "",
            }
        elif current is not None:
            m = _MAC_RE.search(line)
            if m and not current.get("mac"):
                current["mac"] = m.group(1).upper()
                current["vendor"] = (m.group(2) or "").strip()
    if current:
        devices.append(current)
    return devices


def _format_chat_response(local_ip: str, subnet: str,
                          devices: List[Dict[str, Any]]) -> str:
    """Build the ZYRA chat message exactly as the feature spec describes."""
    lines = [
        "Scanning your network...",
        "",
        f"Local IP: {local_ip}",
        f"Network: {subnet}",
        "",
    ]
    if devices:
        lines.append(f"Network scan completed. Devices discovered: {len(devices)}")
        lines.append("")
        for d in devices:
            parts = [d["ip"]]
            if d.get("hostname"):
                parts.append(d["hostname"])
            if d.get("mac"):
                mac_txt = d["mac"]
                if d.get("vendor"):
                    mac_txt += f" ({d['vendor']})"
                parts.append(mac_txt)
            lines.append("• " + " — ".join(parts))
    else:
        lines.append(
            "Network scan completed. No other devices were discovered on "
            "your network."
        )
    return "\n".join(lines)


def scan_my_network() -> Dict[str, Any]:
    """
    THE shared network-scan function (typed chat and voice chat both call it).

    Detects the active local private IPv4, derives and validates its /24
    subnet, runs `nmap -sn <subnet>` host discovery through the existing
    NmapScanner engine and returns a dict with `chat_response` (shown
    directly in the existing ZYRA chat) plus structured device data.
    """
    local_ip, subnet = detect_local_subnet()
    if not local_ip or not subnet:
        msg = (
            "I couldn't detect an active local network interface with a "
            "private IPv4 address. Please make sure you're connected to a "
            "local network (Wi-Fi or Ethernet) and try again."
        )
        return {"success": False, "error": msg, "chat_response": msg}

    # ── Validate the target before executing Nmap ──
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return {
            "success": False,
            "error": f"Derived subnet '{subnet}' is not a valid network.",
            "chat_response": f"I derived an invalid network ({subnet}) and "
                             "refused to scan it.",
        }
    if not _is_private_ipv4(str(network.network_address)):
        msg = (
            f"The detected network ({subnet}) is not a private local "
            "network, so I won't scan it. I only scan your own local "
            "subnet for safety."
        )
        return {"success": False, "error": msg, "chat_response": msg}

    # ── Run Nmap host discovery via the existing scanner engine ──
    try:
        from nmap_scanner import NmapScanner
        scanner = NmapScanner()  # raises RuntimeError if Nmap is not installed
    except Exception as e:  # noqa: BLE001 — surfaced inside the chat
        msg = (
            "I can't scan your network because Nmap is not installed or "
            f"cannot be located on this machine ({e}). Install Nmap and "
            "try again."
        )
        return {"success": False, "error": msg, "chat_response": msg}

    try:
        # Safe argument-list execution (no shell, no unsafe string
        # construction — the target is the validated private local subnet).
        stdout, stderr, returncode = scanner._run_nmap(
            ["-sn", "-T4", subnet], timeout=300
        )
    except Exception as e:  # noqa: BLE001
        msg = f"The network scan failed to run: {e}"
        return {"success": False, "error": msg, "chat_response": msg}

    if returncode != 0:
        err = (stderr or "Nmap exited with an error").strip()[:300]
        msg = f"The network scan failed: {err}"
        return {"success": False, "error": err, "chat_response": msg}

    devices = _parse_ping_sweep_output(stdout)
    devices.sort(key=lambda d: tuple(int(o) for o in d["ip"].split(".")))
    chat = _format_chat_response(local_ip, subnet, devices)
    return {
        "success": True,
        "chat_response": chat,
        "local_ip": local_ip,
        "subnet": subnet,
        "devices": devices,
        "devices_count": len(devices),
    }

