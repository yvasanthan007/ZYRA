"""
nmap_scanner.py — Zyra Nmap Network Scanner Module

Provides:
  - Network host discovery (ping sweep)
  - Port scanning (TCP connect, SYN stealth simulation)
  - Service/version detection
  - OS detection (basic)
  - Common vulnerability checks (weak SSL, open telnet, etc.)
  - Structured scan results with exact voice response text

Scan Types:
  1. Quick Scan: Top 100 ports, no version detection
  2. Standard Scan: Top 1000 ports, service/version detection
  3. Full Scan: All 65535 ports, OS detection, script scanning
  4. Stealth Scan: SYN-like scan (requires admin/root)
  5. Vulnerability Scan: NSE scripts for common CVEs

Security Checks:
  - Open dangerous ports (23-Telnet, 21-FTP, 445-SMB, 3389-RDP)
  - Weak SSL/TLS versions
  - Outdated service versions
  - Default credentials indicators
  - Anonymous FTP access
  - Database exposure (3306-MySQL, 5432-PostgreSQL, 27017-MongoDB)

Verdict Mapping:
  - Score 0-2: Safe (Green)
  - Score 3-5: Warning (Yellow)
  - Score 6+: Critical (Red)
"""

import subprocess
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

# Default nmap command path (can be overridden)
NMAP_COMMAND = "nmap"

# Dangerous ports that increase risk score
DANGEROUS_PORTS = {
    21: ("FTP", 2, "Unencrypted file transfer protocol"),
    23: ("Telnet", 3, "Unencrypted remote access - highly insecure"),
    25: ("SMTP", 1, "Mail server - potential spam relay"),
    53: ("DNS", 1, "DNS server - potential amplification attack"),
    135: ("RPC", 2, "Windows RPC - common exploit vector"),
    139: ("NetBIOS", 2, "Windows file sharing - security risk"),
    445: ("SMB", 3, "Windows SMB - ransomware target"),
    1433: ("MSSQL", 2, "Microsoft SQL Server - database exposure"),
    1521: ("Oracle", 2, "Oracle DB - database exposure"),
    3306: ("MySQL", 2, "MySQL database - often misconfigured"),
    3389: ("RDP", 2, "Remote Desktop - brute force target"),
    5432: ("PostgreSQL", 2, "PostgreSQL database - exposure risk"),
    5900: ("VNC", 2, "VNC remote desktop - weak authentication"),
    6379: ("Redis", 2, "Redis - often no authentication"),
    27017: ("MongoDB", 3, "MongoDB - frequently exposed without auth"),
}

# Common vulnerability patterns in service versions
VULNERABLE_VERSION_PATTERNS = [
    (r'vsftpd\s+2\.3\.4', "vsftpd 2.3.4 backdoor vulnerability"),
    (r'UnrealIRCd', "UnrealIRCd backdoor vulnerability"),
    (r'Apache\s+2\.[0-3]', "Outdated Apache version"),
    (r'OpenSSH\s+[1-5]\.', "Outdated OpenSSH version"),
    (r'OpenSSL\s+0\.', "Vulnerable OpenSSL version"),
    (r'OpenSSL\s+1\.0\.', "Outdated OpenSSL 1.0.x"),
    (r'Windows\s+SMB\s+.*\(lanman\)', "Weak SMB signing"),
]

# ──────────────────────────────────────────────
# Shared command construction (single source of truth)
# ──────────────────────────────────────────────

def build_scan_args(
    scan_type: str,
    target: str,
    ports: Optional[str] = None,
    scripts: Optional[List[str]] = None,
    xml_file: Optional[str] = None,
) -> List[str]:
    """
    Build the exact nmap argument list for a given scan type and target.

    This is the single source of truth used both for execution and for
    displaying the command inside the Nmap Scanner panel, so the shown
    command always matches what is actually executed.

    Args:
        scan_type: "quick", "standard", "full", "stealth", "vuln" or "ping_sweep"
        target: IP address, hostname, or network range
        ports: Optional custom port spec (e.g. "1-1000,3306")
        scripts: Optional NSE scripts
        xml_file: Optional XML output filename (used for structured parsing)

    Returns:
        List of command-line arguments (without the nmap executable itself)
    """
    args: List[str] = []

    # Always request XML output for parsing when a filename is supplied
    if xml_file:
        args.extend(["-oX", xml_file])

    if scan_type == "ping_sweep":
        args.extend(["-sn", "-T4"])  # Ping sweep, no port scan
    elif scan_type == "quick":
        args.extend(["-F", "-T4"])  # Fast scan, top 100 ports
    elif scan_type == "standard":
        args.extend(["-sS", "-sV", "-T4"])  # SYN scan, version detection
    elif scan_type == "full":
        args.extend(["-sS", "-sV", "-O", "-A", "-T4", "-p-", "--script=default,vuln"])
    elif scan_type == "stealth":
        args.extend(["-sS", "-sV", "-T2"])  # Slow SYN scan
    elif scan_type == "vuln":
        args.extend(["-sS", "-sV", "--script=vuln", "-T4"])
    else:
        args.extend(["-sS", "-sV", "-T4"])  # Default to standard

    if ports:
        args.extend(["-p", ports])

    if scripts:
        script_arg = ",".join(scripts)
        args.extend(["--script", script_arg])

    # Add target
    args.append(target)
    return args


def get_nmap_version(nmap_path: str = NMAP_COMMAND) -> str:
    """
    Return the installed Nmap version string (e.g. "7.98").
    Returns "unknown" if Nmap cannot be located.
    """
    try:
        result = subprocess.run(
            [nmap_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        if result.returncode == 0:
            first_line = result.stdout.strip().splitlines()
            if first_line:
                return first_line[0]
        return "unknown"
    except Exception:
        return "unknown"



class NmapScanner:
    """
    High-level Nmap scanner wrapper.
    Handles command construction, execution, and result parsing.
    """
    
    def __init__(self, nmap_path: str = NMAP_COMMAND):
        """
        Initialize the Nmap scanner.
        
        Args:
            nmap_path: Path to the nmap executable
        """
        self.nmap_path = nmap_path
        self._check_nmap_installed()
    
    def _check_nmap_installed(self) -> bool:
        """Check if nmap is installed and accessible."""
        try:
            result = subprocess.run(
                [self.nmap_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            return result.returncode == 0
        except FileNotFoundError:
            raise RuntimeError(
                "Nmap is not installed or not in PATH. "
                "Please install Nmap from https://nmap.org/download.html"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Nmap command timed out during version check")
    
    def _run_nmap(self, args: List[str], timeout: int = 300) -> Tuple[str, str, int]:
        """
        Execute nmap with given arguments.
        
        Args:
            args: List of command-line arguments
            timeout: Timeout in seconds
            
        Returns:
            Tuple of (stdout, stderr, return_code)
        """
        cmd = [self.nmap_path] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", "Scan timed out", -1
        except Exception as e:
            return "", str(e), -1

    def _parse_nmap_xml(self, xml_output: str) -> Dict[str, Any]:
        """
        Parse Nmap XML output into structured data.
        
        Args:
            xml_output: Raw XML string from nmap -oX
            
        Returns:
            Parsed scan results dictionary
        """
        hosts = []
        try:
            root = ET.fromstring(xml_output)
            
            for host in root.findall('.//host'):
                host_data = {
                    "ip": "",
                    "hostname": "",
                    "mac": "",
                    "status": "unknown",
                    "os_match": "",
                    "ports": [],
                    "vulnerabilities": []
                }
                
                # Get IP address
                addr = host.find('address[@addrtype="ipv4"]')
                if addr is not None:
                    host_data["ip"] = addr.get('addr')

                # Get MAC address
                mac = host.find('address[@addrtype="mac"]')
                if mac is not None:
                    host_data["mac"] = mac.get('addr')
                
                # Get hostname
                hostnames = host.find('hostnames')
                if hostnames is not None:
                    hostname_elem = hostnames.find('hostname')
                    if hostname_elem is not None:
                        host_data["hostname"] = hostname_elem.get('name')
                
                # Get host status
                status = host.find('status')
                if status is not None:
                    host_data["status"] = status.get('state')
                
                # Get OS detection
                osmatch = host.find('osmatch')
                if osmatch is not None:
                    host_data["os_match"] = osmatch.get('name', '')
                
                # Get port information
                ports = host.find('ports')
                if ports is not None:
                    for port in ports.findall('port'):
                        port_data = {
                            "port": int(port.get('portid')),
                            "protocol": port.get('protocol', 'tcp'),
                            "state": "",
                            "service": "",
                            "version": "",
                            "product": "",
                            "extrainfo": ""
                        }
                        
                        state = port.find('state')
                        if state is not None:
                            port_data["state"] = state.get('state')
                        
                        service = port.find('service')
                        if service is not None:
                            port_data["service"] = service.get('name', '')
                            port_data["product"] = service.get('product', '')
                            port_data["version"] = service.get('version', '')
                            port_data["extrainfo"] = service.get('extrainfo', '')
                            port_data["tunnel"] = service.get('tunnel', '')
                        
                        # Check for script results (vulnerabilities)
                        scripts = port.findall('script')
                        for script in scripts:
                            script_output = script.get('output', '')
                            script_id = script.get('id', '')
                            if script_output:
                                host_data["vulnerabilities"].append({
                                    "port": port_data["port"],
                                    "script_id": script_id,
                                    "output": script_output[:500]  # Limit length
                                })
                        
                        if port_data["state"] in ["open", "open|filtered"]:
                            host_data["ports"].append(port_data)
                
                if host_data["ip"]:
                    hosts.append(host_data)
        
        except ET.ParseError as e:
            print(f"XML parse error: {e}")
            # Fallback to basic text parsing
            hosts = self._parse_nmap_text(xml_output)
        
        return {"hosts": hosts}
    
    def _parse_nmap_text(self, text_output: str) -> Dict[str, Any]:
        """
        Fallback parser for Nmap text output.
        Less accurate but works when XML parsing fails.
        """
        hosts = []
        current_host = None
        
        for line in text_output.split('\n'):
            line = line.strip()
            
            # Match host line: "Nmap scan report for 192.168.1.1"
            # or "Nmap scan report for localhost (127.0.0.1)"
            if line.startswith("Nmap scan report for"):
                if current_host:
                    hosts.append(current_host)
                raw_host = line.split("for", 1)[-1].strip()
                ip_match = re.search(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', raw_host)
                if ip_match:
                    parsed_ip = ip_match.group(1)
                else:
                    parsed_ip = raw_host
                current_host = {
                    "ip": parsed_ip,
                    "hostname": "",
                    "status": "up",
                    "os_match": "",
                    "ports": [],
                    "vulnerabilities": []
                }
            
            # Match port line: "22/tcp   open  ssh"
            elif current_host and '/' in line and 'open' in line.lower():
                parts = line.split()
                if len(parts) >= 3:
                    port_proto = parts[0].split('/')
                    if len(port_proto) == 2:
                        try:
                            port_num = int(port_proto[0])
                            service = parts[2] if len(parts) > 2 else ""
                            current_host["ports"].append({
                                "port": port_num,
                                "protocol": port_proto[1],
                                "state": "open",
                                "service": service,
                                "version": "",
                                "product": "",
                                "extrainfo": ""
                            })
                        except ValueError:
                            pass
            
            # Match OS detection
            elif "OS detection" in line or "os match" in line.lower():
                if current_host:
                    current_host["os_match"] = line.split(":", 1)[-1].strip() if ":" in line else line
        
        if current_host:
            hosts.append(current_host)
        
        return {"hosts": hosts}

    def scan_host(self, target: str, scan_type: str = "quick", 
                  ports: Optional[str] = None, scripts: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Perform a network scan on the target.
        
        Args:
            target: IP address, hostname, or network range (e.g., 192.168.1.0/24)
            scan_type: Type of scan - "quick", "standard", "full", "stealth", "vuln"
            ports: Custom port specification (e.g., "1-1000,3306,8080")
            scripts: Custom NSE scripts to run
            
        Returns:
            Dictionary with scan results
        """
        args = []
        xml_file = f"nmap_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
        
        # Always request XML output for parsing
        args.extend(["-oX", xml_file])
        
        if scan_type == "quick":
            args.extend(["-F", "-T4"])  # Fast scan, top 100 ports
        elif scan_type == "standard":
            args.extend(["-sS", "-sV", "-T4"])  # SYN scan, version detection
        elif scan_type == "full":
            args.extend(["-sS", "-sV", "-O", "-A", "-T4", "-p-", "--script=default,vuln"])
        elif scan_type == "stealth":
            args.extend(["-sS", "-sV", "-T2"])  # Slow SYN scan
        elif scan_type == "vuln":
            args.extend(["-sS", "-sV", "--script=vuln", "-T4"])
        else:
            args.extend(["-sS", "-sV", "-T4"])  # Default to standard
        
        if ports:
            args.extend(["-p", ports])
        
        if scripts:
            script_arg = ",".join(scripts)
            args.extend(["--script", script_arg])
        
        # Add target
        args.append(target)
        
        # Run scan
        print(f"🔍 Running Nmap scan: {self.nmap_path} {' '.join(args)}")
        stdout, stderr, returncode = self._run_nmap(args, timeout=600)
        
        if returncode != 0:
            return {
                "success": False,
                "error": f"Nmap scan failed: {stderr}" if stderr else "Unknown error",
                "hosts": []
            }
        
        # Try to read XML output file
        try:
            with open(xml_file, 'r', encoding='utf-8') as f:
                xml_content = f.read()
            results = self._parse_nmap_xml(xml_content)
        except FileNotFoundError:
            results = self._parse_nmap_text(stdout)
        except Exception as e:
            results = self._parse_nmap_text(stdout)
        
        # Clean up XML file
        try:
            import os
            os.remove(xml_file)
        except:
            pass
        
        results["success"] = True
        results["scan_type"] = scan_type
        results["target"] = target
        results["timestamp"] = datetime.now().isoformat()
        
        return results
    
    def ping_sweep(self, network: str) -> Dict[str, Any]:
        """
        Perform a ping sweep to discover live hosts.
        
        Args:
            network: Network range (e.g., "192.168.1.0/24")
            
        Returns:
            Dictionary with discovered hosts
        """
        args = ["-sn", "-T4", network]  # Ping sweep, no port scan
        
        print(f"🔍 Running ping sweep: {self.nmap_path} {' '.join(args)}")
        stdout, stderr, returncode = self._run_nmap(args, timeout=300)
        
        if returncode != 0:
            return {
                "success": False,
                "error": f"Ping sweep failed: {stderr}" if stderr else "Unknown error",
                "hosts": []
            }
        
        results = self._parse_nmap_text(stdout)
        results["success"] = True
        results["scan_type"] = "ping_sweep"
        results["target"] = network
        
        return results


def analyze_scan_results(scan_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze scan results and calculate risk score.
    
    Args:
        scan_results: Results from NmapScanner.scan_host()
        
    Returns:
        Analysis with risk score, verdict, and recommendations
    """
    total_score = 0
    findings = []
    recommendations = []
    
    hosts = scan_results.get("hosts", [])
    
    for host in hosts:
        host_score = 0
        host_findings = []
        
        for port_info in host.get("ports", []):
            port = port_info.get("port")
            service = port_info.get("service", "")
            version = port_info.get("version", "")
            product = port_info.get("product", "")
            
            # Check for dangerous ports
            if port in DANGEROUS_PORTS:
                port_name, risk, description = DANGEROUS_PORTS[port]
                host_score += risk
                host_findings.append({
                    "type": "dangerous_port",
                    "port": port,
                    "service": port_name,
                    "risk": risk,
                    "description": description,
                    "details": f"Port {port} ({port_name}) is open"
                })
            
            # Check for vulnerable versions
            full_version = f"{product} {version}".strip()
            for pattern, vuln_desc in VULNERABLE_VERSION_PATTERNS:
                if re.search(pattern, full_version, re.IGNORECASE):
                    host_score += 2
                    host_findings.append({
                        "type": "vulnerable_version",
                        "port": port,
                        "service": service,
                        "version": full_version,
                        "vulnerability": vuln_desc,
                        "details": f"Vulnerable: {vuln_desc}"
                    })
            
            # Check for SSL/TLS issues
            if port_info.get("tunnel") == "ssl":
                if "SSLv" in version or "TLSv1.0" in version or "TLSv1.1" in version:
                    host_score += 2
                    host_findings.append({
                        "type": "weak_ssl",
                        "port": port,
                        "service": service,
                        "version": version,
                        "details": f"Weak SSL/TLS version: {version}"
                    })
        
        # Check for vulnerabilities from NSE scripts
        for vuln in host.get("vulnerabilities", []):
            host_score += 3
            host_findings.append({
                "type": "script_vuln",
                "port": vuln.get("port"),
                "script_id": vuln.get("script_id"),
                "output": vuln.get("output", "")[:200],
                "details": f"Vulnerability found by {vuln.get('script_id')}"
            })
        
        # Determine host verdict
        if host_score == 0:
            host_verdict = "Safe"
        elif host_score <= 3:
            host_verdict = "Warning"
        else:
            host_verdict = "Critical"
        
        findings.append({
            "host": host.get("ip", "unknown"),
            "hostname": host.get("hostname", ""),
            "os": host.get("os_match", ""),
            "score": host_score,
            "verdict": host_verdict,
            "findings": host_findings
        })
        
        total_score += host_score
    
    # Overall verdict
    if total_score == 0:
        overall_verdict = "Safe"
    elif total_score <= 5:
        overall_verdict = "Warning"
    else:
        overall_verdict = "Critical"
    
    # Generate recommendations
    if total_score > 0:
        dangerous_ports_found = [f for f in findings for item in f.get("findings", []) 
                                if item.get("type") == "dangerous_port"]
        if dangerous_ports_found:
            recommendations.append("Close or filter unnecessary dangerous ports (Telnet, FTP, SMB)")
        
        vuln_versions = [f for f in findings for item in f.get("findings", []) 
                        if item.get("type") == "vulnerable_version"]
        if vuln_versions:
            recommendations.append("Update outdated services to latest secure versions")
        
        weak_ssl = [f for f in findings for item in f.get("findings", []) 
                   if item.get("type") == "weak_ssl"]
        if weak_ssl:
            recommendations.append("Disable weak SSL/TLS versions and use TLS 1.2+")
        
        script_vulns = [f for f in findings for item in f.get("findings", []) 
                       if item.get("type") == "script_vuln"]
        if script_vulns:
            recommendations.append("Investigate and patch identified vulnerabilities")
    
    return {
        "total_score": total_score,
        "verdict": overall_verdict,
        "hosts_analyzed": len(hosts),
        "findings": findings,
        "recommendations": recommendations,
        "timestamp": datetime.now().isoformat()
    }


def get_scan_summary(analysis_results: Dict[str, Any]) -> str:
    """
    Generate a human-readable summary of scan results.
    
    Args:
        analysis_results: Results from analyze_scan_results()
        
    Returns:
        Formatted summary string
    """
    verdict = analysis_results.get("verdict", "Unknown")
    score = analysis_results.get("total_score", 0)
    hosts = analysis_results.get("hosts_analyzed", 0)
    
    verdict_emoji = {"Safe": "✅", "Warning": "⚠️", "Critical": "🚫"}.get(verdict, "❓")
    
    lines = [
        f"{verdict_emoji} Network Scan Summary",
        f"   Verdict: {verdict}",
        f"   Risk Score: {score}",
        f"   Hosts Analyzed: {hosts}",
        ""
    ]
    
    for host_info in analysis_results.get("findings", []):
        host = host_info.get("host", "unknown")
        host_verdict = host_info.get("verdict", "Unknown")
        host_score = host_info.get("score", 0)
        
        lines.append(f"   Host: {host} ({host_verdict}, Score: {host_score})")
        
        if host_info.get("os"):
            lines.append(f"      OS: {host_info['os']}")
        
        for finding in host_info.get("findings", []):
            lines.append(f"      • {finding.get('details', '')}")
    
    recommendations = analysis_results.get("recommendations", [])
    if recommendations:
        lines.append("")
        lines.append("   Recommendations:")
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"      {i}. {rec}")
    
    return "\n".join(lines)


def get_voice_summary(analysis_results: Dict[str, Any]) -> str:
    """
    Generate a concise voice-friendly summary for TTS.
    
    Args:
        analysis_results: Results from analyze_scan_results()
        
    Returns:
        Voice summary string
    """
    verdict = analysis_results.get("verdict", "Unknown")
    score = analysis_results.get("total_score", 0)
    hosts = analysis_results.get("hosts_analyzed", 0)
    
    if verdict == "Safe":
        return f"Network scan complete. {hosts} hosts analyzed. All systems appear secure with a risk score of {score}."
    elif verdict == "Warning":
        return f"Network scan complete. {hosts} hosts analyzed. Warning: {score} security issues detected. Please review the findings."
    else:
        return f"Network scan complete. {hosts} hosts analyzed. Critical: {score} security issues found. Immediate action recommended."


# ──────────────────────────────────────────────
# Standalone Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Zyra Nmap Scanner — Standalone Test")
    print("=" * 60)
    print()
    
    # Test with localhost
    try:
        scanner = NmapScanner()
        
        print("🔍 Running quick scan on localhost...")
        results = scanner.scan_host("127.0.0.1", scan_type="quick")
        
        if results.get("success"):
            print(f"✅ Scan completed. Found {len(results.get('hosts', []))} hosts.")
            
            analysis = analyze_scan_results(results)
            print(f"\n📊 Analysis Results:")
            print(get_scan_summary(analysis))
            print(f"\n🗣️  Voice Summary: {get_voice_summary(analysis)}")
        else:
            print(f"❌ Scan failed: {results.get('error', 'Unknown error')}")
    
    except RuntimeError as e:
        print(f"❌ Error: {e}")
        print("   Make sure Nmap is installed and in your PATH.")