"""
nmap_handler.py — Zyra Nmap Network Scanner Intent Handler

Features:
- Detects network scanning requests.
- Extracts IP addresses and network targets.
- Supports quick, standard, full, stealth, vulnerability, and ping-sweep scans.
- Analyzes scan results and reports findings.
- Provides optional speech output.
- Allows the module to load when pygame or the speech engine is unavailable.

IMPORTANT:
Only scan systems and networks you own or have explicit permission to test.
"""

import re
from typing import Optional, Dict, Any


# ============================================================
# OPTIONAL SPEECH
# ============================================================

try:
    from speak import speak as _speak

    def speak(text: str, *args, **kwargs):
        """Use Zyra's speech engine when it is available."""
        try:
            return _speak(text, *args, **kwargs)
        except Exception as exc:
            print(f"[Zyra/Nmap] Speech playback unavailable: {exc}")
            return None

except Exception as exc:
    print(
        "[Zyra/Nmap] Speech engine unavailable. "
        f"Continuing without audio: {exc}"
    )

    def speak(text: str, *args, **kwargs):
        """Fallback speech function when audio is unavailable."""
        if text:
            print(f"[Zyra/Nmap] {text}")
        return None


# ============================================================
# NMAP SCANNER IMPORT
# ============================================================

_NMAP_IMPORT_ERROR = None

try:
    from nmap_scanner import (
        NmapScanner,
        analyze_scan_results,
        get_voice_summary,
        get_scan_summary,
    )
except Exception as exc:
    _NMAP_IMPORT_ERROR = exc

    print(
        "[Zyra/Nmap] Scanner module could not be loaded: "
        f"{type(exc).__name__}: {exc}"
    )

    NmapScanner = None
    analyze_scan_results = None
    get_voice_summary = None
    get_scan_summary = None


# ============================================================
# PERSONA
# ============================================================

NMAP_PERSONA = (
    "NETWORK SECURITY MODE: Zyra can perform network scanning "
    "using Nmap. When asked to scan an authorized network, Zyra "
    "can discover hosts, open ports, services, and potential "
    "security issues. Scan results must be interpreted carefully "
    "and do not guarantee that a system is completely safe."
)


# ============================================================
# INTENT TRIGGERS
# ============================================================

NMAP_TRIGGERS = [
    "scan the network",
    "scan network",
    "network scan",
    "run nmap",
    "start nmap",
    "open nmap",
    "launch nmap",
    "check network security",
    "check network",
    "network security scan",
    "port scan",
    "scan ports",
    "scan my network",
    "scan local network",
    "discover hosts",
    "ping sweep",
    "vulnerability scan",
    "vuln scan",
    "security scan",
    "check for open ports",
    "check for vulnerabilities",
    "is my network secure",
    "network analysis",
    "analyze network",
]


# ============================================================
# INTENT DETECTION
# ============================================================

def is_nmap_intent(text: str) -> bool:
    """
    Return True when the supplied text appears to request a scan.
    """
    if not text or not isinstance(text, str):
        return False

    text_lower = text.lower().strip()

    if any(trigger in text_lower for trigger in NMAP_TRIGGERS):
        return True

    ip_pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b"

    if re.search(ip_pattern, text_lower):
        scan_words = ("scan", "check", "analyze", "nmap")
        if any(word in text_lower for word in scan_words):
            return True

    if "scan" in text_lower and (
        "ip" in text_lower or "host" in text_lower
    ):
        return True

    return False


# ============================================================
# TARGET EXTRACTION
# ============================================================

def extract_target_from_command(text: str) -> Optional[str]:
    """
    Extract an IPv4 address, CIDR target, or basic hostname.

    If no target is supplied, return None. The caller decides
    whether to use localhost as a default.
    """
    if not text or not isinstance(text, str):
        return None

    text_lower = text.lower().strip()

    # Prefer explicit IPv4/CIDR targets.
    ip_pattern = (
        r"\b("
        r"(?:\d{1,3}\.){3}\d{1,3}"
        r"(?:/\d{1,2})?"
        r")\b"
    )

    match = re.search(ip_pattern, text)
    if match:
        return match.group(1)

    # Look for a hostname following common target keywords.
    hostname_pattern = (
        r"\b(?:scan|check|analyze|target|on|against)\s+"
        r"([a-zA-Z0-9]"
        r"(?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?)"
    )

    for match in re.finditer(hostname_pattern, text, re.IGNORECASE):
        candidate = match.group(1).rstrip(".")

        ignored_words = {
            "the",
            "network",
            "my",
            "local",
            "ports",
            "for",
            "vulnerabilities",
            "security",
            "host",
            "ip",
        }

        if candidate.lower() not in ignored_words:
            if "." in candidate or candidate.lower() == "localhost":
                return candidate

    if "local network" in text_lower or "my network" in text_lower:
        return "192.168.1.0/24"

    if "localhost" in text_lower or "this computer" in text_lower:
        return "127.0.0.1"

    return None


# ============================================================
# SCAN TYPE
# ============================================================

def extract_scan_type(text: str) -> str:
    """
    Determine the requested scan type.

    Supported types depend on nmap_scanner.py.
    """
    text_lower = (text or "").lower().strip()

    if "vulnerability" in text_lower or "vuln" in text_lower:
        return "vuln"

    if any(word in text_lower for word in ("full", "complete", "deep")):
        return "full"

    if any(word in text_lower for word in ("stealth", "slow", "quiet")):
        return "stealth"

    if any(word in text_lower for word in ("fast", "quick", "quickly")):
        return "quick"

    if "ping sweep" in text_lower or "discover" in text_lower:
        return "ping_sweep"

    return "standard"


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _scanner_unavailable_message() -> str:
    if _NMAP_IMPORT_ERROR:
        return (
            "The Nmap scanner could not be loaded. "
            "Check its dependencies and the Python console for details."
        )

    return (
        "The Nmap scanner is unavailable. "
        "Check that Nmap and its Python dependencies are installed."
    )


def _create_scanner():
    """
    Create a scanner or raise a useful error.
    """
    if NmapScanner is None:
        raise RuntimeError(_scanner_unavailable_message())

    try:
        return NmapScanner()
    except Exception as exc:
        raise RuntimeError(
            f"Unable to initialize Nmap: {exc}"
        ) from exc


def _run_scan(scanner, target: str, scan_type: str):
    """
    Run the appropriate scan method.
    """
    if scan_type == "ping_sweep":
        return scanner.ping_sweep(target)

    return scanner.scan_host(target, scan_type=scan_type)


def _analyze_results(results: Dict[str, Any]):
    """
    Analyze scan results and validate that the analyzer is available.
    """
    if analyze_scan_results is None:
        raise RuntimeError(
            "The Nmap results analyzer is unavailable."
        )

    return analyze_scan_results(results)


def _build_speech_summary(analysis: Dict[str, Any]) -> str:
    """
    Generate a readable summary, with a safe fallback.
    """
    if get_voice_summary is not None:
        try:
            summary = get_voice_summary(analysis)
            if summary:
                return str(summary)
        except Exception as exc:
            print(f"[Zyra/Nmap] Summary generation warning: {exc}")

    verdict = analysis.get("verdict", "Unknown")
    score = analysis.get("total_score", 0)

    return (
        f"Network scan completed. "
        f"Overall verdict: {verdict}. "
        f"Risk score: {score}."
    )


def _error_result(
    message: str,
    target: Optional[str] = None,
    scan_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a consistent failure response.
    """
    return {
        "success": False,
        "error": message,
        "target": target,
        "scan_type": scan_type,
        "speech_text": message,
    }


# ============================================================
# MAIN NMAP INTENT HANDLER
# ============================================================

def handle_nmap_intent(
    user_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parse a scan request, run the scan, analyze the results,
    and return structured output.

    Audio playback is optional and will not crash this handler.
    """
    print("\n" + "=" * 60)
    print("ZYRA NETWORK SCANNER — NMAP INTEGRATION")
    print("=" * 60)

    target = (
        extract_target_from_command(user_text)
        if user_text
        else None
    )

    scan_type = (
        extract_scan_type(user_text)
        if user_text
        else "standard"
    )

    if not target:
        target = "127.0.0.1"
        print(f"[Zyra/Nmap] No target specified; using {target}")
    else:
        print(f"[Zyra/Nmap] Target: {target}")

    print(f"[Zyra/Nmap] Scan type: {scan_type}")

    try:
        scanner = _create_scanner()
    except Exception as exc:
        message = str(exc)
        print(f"[Zyra/Nmap] Scanner initialization failed: {message}")
        speak(message)
        return _error_result(message, target, scan_type)

    try:
        results = _run_scan(scanner, target, scan_type)

        if not isinstance(results, dict):
            message = "The scanner returned an unexpected response."
            print(f"[Zyra/Nmap] {message}")
            return _error_result(message, target, scan_type)

        if not results.get("success"):
            message = str(
                results.get("error", "The network scan failed.")
            )
            print(f"[Zyra/Nmap] Scan failed: {message}")
            speak(message)
            return _error_result(message, target, scan_type)

    except Exception as exc:
        message = f"Scan execution failed: {exc}"
        print(f"[Zyra/Nmap] {message}")
        speak("I encountered an error while running the network scan.")
        return _error_result(message, target, scan_type)

    try:
        analysis = _analyze_results(results)
    except Exception as exc:
        message = f"Scan completed, but result analysis failed: {exc}"
        print(f"[Zyra/Nmap] {message}")
        return {
            "success": False,
            "error": message,
            "target": target,
            "scan_type": scan_type,
            "raw_results": results,
        }

    verdict = analysis.get("verdict", "Unknown")
    score = analysis.get("total_score", 0)
    findings = analysis.get("findings", [])
    recommendations = analysis.get("recommendations", [])

    verdict_emoji = {
        "Safe": "[SAFE]",
        "Warning": "[WARNING]",
        "Critical": "[CRITICAL]",
    }.get(verdict, "[UNKNOWN]")

    print("\n" + "=" * 60)
    print("NETWORK SCAN REPORT")
    print("=" * 60)
    print(f"Target: {target}")
    print(f"Scan type: {scan_type}")
    print(f"Verdict: {verdict_emoji} {verdict}")
    print(f"Risk score: {score}")
    print(f"Hosts analyzed: {len(findings)}")

    for host_info in findings:
        print(
            "\nHost: "
            f"{host_info.get('host', 'unknown')} "
            f"({host_info.get('verdict', 'Unknown')}, "
            f"score: {host_info.get('score', 0)})"
        )

        if host_info.get("os"):
            print(f"  OS: {host_info['os']}")

        for finding in host_info.get("findings", []):
            print(
                "  - "
                + str(finding.get("details", finding))
            )

    if recommendations:
        print("\nRecommendations:")
        for index, recommendation in enumerate(recommendations, 1):
            print(f"  {index}. {recommendation}")

    speech_text = _build_speech_summary(analysis)
    print(f"\nSummary: {speech_text}")

    # Speech is optional and must not invalidate a successful scan.
    speak(speech_text)

    print("=" * 60)

    return {
        "success": True,
        "target": target,
        "scan_type": scan_type,
        "analysis": analysis,
        "speech_text": speech_text,
        "raw_results": results,
        "timestamp": analysis.get("timestamp"),
    }


# ============================================================
# QUICK SCAN
# ============================================================

def quick_scan(
    target: str,
    scan_type: str = "quick",
) -> Dict[str, Any]:
    """
    Scan a specified target directly.

    Only use this function on authorized targets.
    """
    if not target or not isinstance(target, str):
        return _error_result("A valid target is required.")

    print(f"\n[Zyra/Nmap] Scanning target: {target}")

    try:
        scanner = _create_scanner()
        results = _run_scan(scanner, target, scan_type)

        if not isinstance(results, dict):
            return _error_result(
                "The scanner returned an unexpected response.",
                target,
                scan_type,
            )

        if not results.get("success"):
            return _error_result(
                str(results.get("error", "Scan failed.")),
                target,
                scan_type,
            )

        analysis = _analyze_results(results)
        speech_text = _build_speech_summary(analysis)

        speak(speech_text)

        return {
            "success": True,
            "target": target,
            "scan_type": scan_type,
            "analysis": analysis,
            "speech_text": speech_text,
            "raw_results": results,
            "timestamp": analysis.get("timestamp"),
        }

    except Exception as exc:
        message = f"Quick scan failed: {exc}"
        print(f"[Zyra/Nmap] {message}")
        return _error_result(message, target, scan_type)


# ============================================================
# COMMAND-LINE TEST
# ============================================================

if __name__ == "__main__":
    import sys

    print(
        """
==============================================
       ZYRA NETWORK SCANNER — TEST
==============================================
1. Test command parsing and scan
2. Test a specific authorized target
3. Exit
"""
    )

    choice = input("Enter choice (1-3): ").strip()

    if choice == "1":
        command = input(
            "Enter scan command (e.g. scan localhost): "
        ).strip()

        if command:
            result = handle_nmap_intent(command)
            print("\nResult summary:")
            print(f"Success: {result.get('success')}")
            print(f"Target: {result.get('target')}")

            if result.get("error"):
                print(f"Error: {result['error']}")

    elif choice == "2":
        target = input(
            "Enter an authorized IP address or hostname: "
        ).strip()

        if target:
            scan_type = (
                input(
                    "Scan type (quick/standard/full/stealth/vuln) "
                    "[default: quick]: "
                ).strip()
                or "quick"
            )

            result = quick_scan(target, scan_type)

            print("\nResult summary:")
            print(f"Success: {result.get('success')}")

            if result.get("error"):
                print(f"Error: {result['error']}")

            if result.get("analysis"):
                print(
                    "Verdict: "
                    f"{result['analysis'].get('verdict', 'Unknown')}"
                )
    else:
        print("Exiting.")
        sys.exit(0)