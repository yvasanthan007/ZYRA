"""
nmap_handler.py — Zyra Nmap Network Scanner Intent Handler

Main integration handler that ties together:
  - nmap_scanner.py (Nmap network scanning engine)
  - speak.py (Text-to-Speech output)

This module provides the handle_nmap_intent() function that:
  1. Listens for trigger phrases like "Zyra scan the network"
  2. Extracts target IP/hostname from the command
  3. Runs the appropriate scan type
  4. Speaks the results directly to the user

Trigger Phrases:
  - "scan the network"
  - "scan network"
  - "network scan"
  - "run nmap"
  - "scan [IP address]"
  - "check ports on [IP]"
  - "is [IP] secure"
  - "vulnerability scan"
  - "ping sweep"
"""

import re
from typing import Optional, Dict, Any, List

from nmap_scanner import NmapScanner, analyze_scan_results, get_voice_summary, get_scan_summary
from speak import speak


# ──────────────────────────────────────────────
# Persona Definition for AI System Prompt
# ──────────────────────────────────────────────

NMAP_PERSONA = (
    "NETWORK SECURITY MODE: Zyra can perform network scanning using Nmap. "
    "When asked to scan networks or check for vulnerabilities, Zyra uses "
    "real Nmap scans to discover hosts, open ports, services, and security issues. "
    "This is a real security assessment tool, not simulated."
)


# ──────────────────────────────────────────────
# Trigger Phrase Detection
# ──────────────────────────────────────────────

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


def is_nmap_intent(text: str) -> bool:
    """
    Check if the user's text matches an Nmap scanning trigger phrase.
    
    Args:
        text: User's voice command or text input
        
    Returns:
        bool: True if this is an Nmap scanning request
    """
    if not text:
        return False
    
    text_lower = text.lower().strip()
    
    # Check for trigger phrases
    for trigger in NMAP_TRIGGERS:
        if trigger in text_lower:
            return True
    
    # Check for IP address patterns (e.g., "scan 192.168.1.1")
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b'
    if re.search(ip_pattern, text_lower):
        # Also check for scanning verbs
        if any(word in text_lower for word in ["scan", "check", "analyze", "nmap"]):
            return True
    
    # Check for "scan" + IP-like patterns
    if "scan" in text_lower and ("ip" in text_lower or "host" in text_lower):
        return True
    
    return False


def extract_target_from_command(text: str) -> Optional[str]:
    """
    Extract target IP address or hostname from the command.
    
    Args:
        text: User's command text
        
    Returns:
        Target IP/hostname if found, None otherwise
    """
    if not text:
        return None
    
    text_lower = text.lower().strip()
    
    # Look for IP address pattern
    ip_pattern = r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?)\b'
    match = re.search(ip_pattern, text)
    if match:
        return match.group(1)
    
    # Look for common target keywords followed by IP-like text
    for keyword in ["scan", "check", "analyze", "target"]:
        if keyword in text_lower:
            idx = text_lower.find(keyword)
            remaining = text[idx + len(keyword):]
            match = re.search(ip_pattern, remaining)
            if match:
                return match.group(1)
    
    # Default targets based on context
    if "local network" in text_lower or "my network" in text_lower:
        return "192.168.1.0/24"
    elif "localhost" in text_lower or "this computer" in text_lower:
        return "127.0.0.1"
    
    return None


def extract_scan_type(text: str) -> str:
    """
    Determine the scan type from the command.
    
    Args:
        text: User's command text
        
    Returns:
        Scan type: "quick", "standard", "full", "stealth", "vuln"
    """
    text_lower = text.lower().strip()
    
    if "vulnerability" in text_lower or "vuln" in text_lower:
        return "vuln"
    elif "full" in text_lower or "complete" in text_lower or "deep" in text_lower:
        return "full"
    elif "stealth" in text_lower or "slow" in text_lower or "quiet" in text_lower:
        return "stealth"
    elif "fast" in text_lower or "quick" in text_lower or "quickly" in text_lower:
        return "quick"
    elif "ping sweep" in text_lower or "discover" in text_lower:
        return "ping_sweep"
    else:
        return "standard"


def handle_nmap_intent(user_text: Optional[str] = None) -> Dict[str, Any]:
    """
    Main entry point for Nmap scanning intent handling.
    
    This function:
    1. Extracts target and scan type from user command
    2. Runs the Nmap scan
    3. Analyzes results and calculates risk score
    4. Speaks the results directly to the user
    5. Returns structured result
    
    Args:
        user_text: Optional user command text
        
    Returns:
        dict: Complete scan result containing:
            - target: The scanned target
            - scan_type: Type of scan performed
            - success: Whether scan completed successfully
            - analysis: Analysis results with verdict and score
            - speech_text: Exact string that was spoken
            - raw_results: Raw Nmap scan results
    """
    print("\n" + "=" * 60)
    print("🔍 ZYRA NETWORK SCANNER — NMAP INTEGRATION")
    print("=" * 60)
    
    # Step 1: Parse command to extract target and scan type
    print("\n📝 Step 1: Parsing command...")
    target = extract_target_from_command(user_text) if user_text else None
    scan_type = extract_scan_type(user_text) if user_text else "standard"
    
    # Default target if none found
    if not target:
        target = "127.0.0.1"
        print(f"   ℹ️  No target specified, defaulting to localhost ({target})")
    else:
        print(f"   🎯 Target: {target}")
    
    print(f"   📊 Scan type: {scan_type}")
    
    # Step 2: Initialize Nmap scanner
    print("\n🔧 Step 2: Initializing Nmap scanner...")
    try:
        scanner = NmapScanner()
        print("   ✅ Nmap scanner ready")
    except RuntimeError as e:
        error_msg = str(e)
        print(f"   ❌ Error: {error_msg}")
        speech_text = "I'm sorry, but Nmap is not installed on this system. Please install Nmap from nmap.org to use network scanning features."
        speak(speech_text)
        return {
            "success": False,
            "error": error_msg,
            "target": target,
            "scan_type": scan_type,
            "speech_text": speech_text
        }
    
    # Step 3: Run the scan
    print(f"\n🚀 Step 3: Running {scan_type} scan on {target}...")
    try:
        if scan_type == "ping_sweep":
            results = scanner.ping_sweep(target)
        else:
            results = scanner.scan_host(target, scan_type=scan_type)
        
        if not results.get("success"):
            error_msg = results.get("error", "Unknown scan error")
            print(f"   ❌ Scan failed: {error_msg}")
            speech_text = f"Network scan failed. {error_msg}"
            speak(speech_text)
            return {
                "success": False,
                "error": error_msg,
                "target": target,
                "scan_type": scan_type,
                "speech_text": speech_text
            }
        
        hosts_found = len(results.get("hosts", []))
        print(f"   ✅ Scan completed. Found {hosts_found} hosts.")
        
    except Exception as e:
        error_msg = f"Scan execution error: {str(e)}"
        print(f"   ❌ Error: {error_msg}")
        speech_text = "I encountered an error while running the network scan."
        speak(speech_text)
        return {
            "success": False,
            "error": error_msg,
            "target": target,
            "scan_type": scan_type,
            "speech_text": speech_text
        }
    
    # Step 4: Analyze results
    print("\n📈 Step 4: Analyzing scan results...")
    analysis = analyze_scan_results(results)
    
    verdict = analysis.get("verdict", "Unknown")
    score = analysis.get("total_score", 0)
    verdict_emoji = {"Safe": "✅", "Warning": "⚠️", "Critical": "🚫"}.get(verdict, "❓")
    
    print(f"   📊 Overall verdict: {verdict_emoji} {verdict}")
    print(f"   📈 Risk score: {score}")
    print(f"   🔍 Hosts analyzed: {len(analysis.get('findings', []))}")
    
    # Step 5: Generate voice summary and speak
    print("\n🗣️  Step 5: Speaking results...")
    speech_text = get_voice_summary(analysis)
    print(f"   Speech text: {speech_text}")
    speak(speech_text)
    
    # Step 6: Print detailed results
    print("\n" + "=" * 60)
    print("📊 DETAILED SCAN REPORT")
    print("=" * 60)
    print(f"\n🎯 Target: {target}")
    print(f"📊 Scan type: {scan_type}")
    print(f"⚖️  Verdict: {verdict_emoji} {verdict}")
    print(f"📈 Risk score: {score}")
    
    print(f"\n🔍 Host Analysis ({len(analysis.get('findings', []))} hosts):")
    for host_info in analysis.get("findings", []):
        host = host_info.get("host", "unknown")
        host_verdict = host_info.get("verdict", "Unknown")
        host_score = host_info.get("score", 0)
        
        print(f"\n   Host: {host} ({host_verdict}, Score: {host_score})")
        
        if host_info.get("os"):
            print(f"      OS: {host_info['os']}")
        
        findings = host_info.get("findings", [])
        if findings:
            print(f"      Findings:")
            for finding in findings:
                print(f"        • {finding.get('details', '')}")
    
    recommendations = analysis.get("recommendations", [])
    if recommendations:
        print(f"\n💡 Recommendations:")
        for i, rec in enumerate(recommendations, 1):
            print(f"   {i}. {rec}")
    
    print("\n" + "=" * 60)
    
    # Return structured result
    return {
        "success": True,
        "target": target,
        "scan_type": scan_type,
        "analysis": analysis,
        "speech_text": speech_text,
        "raw_results": results,
        "timestamp": analysis.get("timestamp")
    }


def quick_scan(target: str, scan_type: str = "quick") -> Dict[str, Any]:
    """
    Quick scan of a specific target (bypasses command parsing).
    Useful for testing or direct scanning.
    
    Args:
        target: IP address or hostname to scan
        scan_type: Type of scan to perform
        
    Returns:
        dict: Scan result
    """
    print(f"\n🔍 Quick scanning target: {target}")
    
    try:
        scanner = NmapScanner()
        
        if scan_type == "ping_sweep":
            results = scanner.ping_sweep(target)
        else:
            results = scanner.scan_host(target, scan_type=scan_type)
        
        if results.get("success"):
            analysis = analyze_scan_results(results)
            speech_text = get_voice_summary(analysis)
            speak(speech_text)
            
            return {
                "success": True,
                "target": target,
                "scan_type": scan_type,
                "analysis": analysis,
                "speech_text": speech_text,
                "raw_results": results
            }
        else:
            return {
                "success": False,
                "error": results.get("error", "Scan failed"),
                "target": target,
                "scan_type": scan_type
            }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "target": target,
            "scan_type": scan_type
        }


# ──────────────────────────────────────────────
# Command Line Interface
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    print("""
╔══════════════════════════════════════════════╗
║     ZYRA NETWORK SCANNER — TEST              ║
╚══════════════════════════════════════════════╝
    """)
    
    print("Options:")
    print("  1. Test with voice command parsing")
    print("  2. Test with specific target")
    print("  3. Exit")
    print()
    
    choice = input("Enter choice (1-3): ").strip()
    
    if choice == "1":
        command = input("\nEnter command (e.g., 'scan network 192.168.1.1'): ").strip()
        if command:
            result = handle_nmap_intent(command)
            
            print("\n" + "=" * 60)
            print("RESULT SUMMARY")
            print("=" * 60)
            print(f"Success: {result.get('success')}")
            if result.get('success'):
                print(f"Target: {result['target']}")
                print(f"Verdict: {result['analysis']['verdict']}")
                print(f"Speech: {result['speech_text']}")
        else:
            print("No command provided.")
    
    elif choice == "2":
        target = input("\nEnter target IP/hostname: ").strip()
        if target:
            scan_type = input("Enter scan type (quick/standard/full/stealth/vuln) [default: quick]: ").strip() or "quick"
            result = quick_scan(target, scan_type)
            
            print("\n" + "=" * 60)
            print("RESULT SUMMARY")
            print("=" * 60)
            print(f"Success: {result.get('success')}")
            if result.get('success'):
                print(f"Verdict: {result['analysis']['verdict']}")
                print(f"Speech: {result['speech_text']}")
        else:
            print("No target provided.")
    
    else:
        print("Exiting...")
        sys.exit(0)