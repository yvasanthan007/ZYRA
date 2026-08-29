"""
test_nmap_scanner.py — Unit Tests for Zyra Nmap Network Scanner

Tests: dangerous ports, vulnerable patterns, intent recognition,
target/scan type extraction, result analysis, voice summary.
Note: Does not require Nmap to be installed.
"""

import unittest
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDangerousPorts(unittest.TestCase):
    """Tests for dangerous port detection."""
    
    def test_dangerous_ports_defined(self):
        """Test that dangerous ports dictionary is properly defined."""
        from nmap_scanner import DANGEROUS_PORTS
        self.assertIn(23, DANGEROUS_PORTS)
        self.assertIn(445, DANGEROUS_PORTS)
        self.assertIn(3389, DANGEROUS_PORTS)
    
    def test_dangerous_ports_structure(self):
        """Test that dangerous port entries have correct structure."""
        from nmap_scanner import DANGEROUS_PORTS
        for port, (name, risk, description) in DANGEROUS_PORTS.items():
            self.assertIsInstance(name, str)
            self.assertIsInstance(risk, int)
            self.assertGreaterEqual(risk, 1)
            self.assertLessEqual(risk, 3)


class TestVulnerableVersionPatterns(unittest.TestCase):
    """Tests for vulnerable version pattern detection."""
    
    def test_patterns_defined(self):
        """Test that vulnerable version patterns are defined."""
        from nmap_scanner import VULNERABLE_VERSION_PATTERNS
        self.assertGreater(len(VULNERABLE_VERSION_PATTERNS), 0)
    
    def test_patterns_valid_regex(self):
        """Test that all patterns are valid regex."""
        from nmap_scanner import VULNERABLE_VERSION_PATTERNS
        for pattern, description in VULNERABLE_VERSION_PATTERNS:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error:
                self.fail(f"Invalid regex: {pattern}")


class TestNmapHandler(unittest.TestCase):
    """Tests for the Nmap handler functions."""
    
    def test_is_nmap_intent_triggers(self):
        """Test that trigger phrases are recognized."""
        from nmap_handler import is_nmap_intent
        triggers = ["scan the network", "network scan", "run nmap", "port scan"]
        for phrase in triggers:
            self.assertTrue(is_nmap_intent(phrase), f"Failed: {phrase}")
    
    def test_is_nmap_intent_negative(self):
        """Test that non-nmap commands are not recognized."""
        from nmap_handler import is_nmap_intent
        negatives = ["open chrome", "what time is it", "", None]
        for phrase in negatives:
            self.assertFalse(is_nmap_intent(phrase), f"False positive: {phrase}")
    
    def test_extract_target_ip(self):
        """Test target extraction from commands."""
        from nmap_handler import extract_target_from_command
        test_cases = [
            ("scan 192.168.1.1", "192.168.1.1"),
            ("localhost scan", "127.0.0.1"),
            ("scan local network", "192.168.1.0/24"),
        ]
        for command, expected in test_cases:
            result = extract_target_from_command(command)
            self.assertEqual(result, expected, f"Failed: {command}")
    
    def test_extract_scan_type(self):
        """Test scan type extraction from commands."""
        from nmap_handler import extract_scan_type
        test_cases = [
            ("quick scan", "quick"),
            ("full network scan", "full"),
            ("vulnerability scan", "vuln"),
            ("scan network", "standard"),
        ]
        for command, expected in test_cases:
            result = extract_scan_type(command)
            self.assertEqual(result, expected, f"Failed: {command}")


class TestAnalyzeScanResults(unittest.TestCase):
    """Tests for scan result analysis."""
    
    def test_safe_results(self):
        """Test analysis of safe scan results."""
        from nmap_scanner import analyze_scan_results
        safe_results = {"hosts": [{"ip": "192.168.1.1", "ports": []}]}
        analysis = analyze_scan_results(safe_results)
        self.assertEqual(analysis["verdict"], "Safe")
    
    def test_dangerous_results(self):
        """Test analysis of dangerous scan results."""
        from nmap_scanner import analyze_scan_results
        dangerous_results = {"hosts": [{"ip": "192.168.1.100", "ports": [
            {"port": 23, "service": "telnet"}, {"port": 445, "service": "smb"}
        ]}]}
        analysis = analyze_scan_results(dangerous_results)
        self.assertEqual(analysis["verdict"], "Critical")


class TestResolveNmapPath(unittest.TestCase):
    """Tests for Nmap executable auto-detection."""

    def test_env_override_wins(self):
        """The ZYRA_NMAP_PATH env var override is honored first."""
        import os
        import tempfile
        from nmap_scanner import resolve_nmap_path

        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "nmap.exe")
            with open(fake, "w") as f:
                f.write("fake")
            old = os.environ.get("ZYRA_NMAP_PATH")
            os.environ["ZYRA_NMAP_PATH"] = fake
            try:
                self.assertEqual(resolve_nmap_path(), fake)
            finally:
                if old is None:
                    os.environ.pop("ZYRA_NMAP_PATH", None)
                else:
                    os.environ["ZYRA_NMAP_PATH"] = old

    def test_missing_raises_guidance(self):
        """Missing Nmap produces a helpful RuntimeError."""
        from unittest.mock import patch
        from nmap_scanner import resolve_nmap_path

        # Isolate from any real Nmap installs on this machine.
        fake_env = {
            "LOCALAPPDATA": "Z:\\zyra_tests\\nonexistent",
            "ProgramFiles": "Z:\\zyra_tests\\nonexistent",
            "ProgramFiles(x86)": "Z:\\zyra_tests\\nonexistent",
            "SystemDrive": "Z:",
        }
        with patch("nmap_scanner.os.environ", fake_env), \
             patch("nmap_scanner._NMAP_CANDIDATE_PATHS", []), \
             patch("nmap_scanner.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                resolve_nmap_path()
            self.assertIn("nmap.org", str(ctx.exception))

    def test_nmap_scanner_accepts_explicit_path(self):
        """An explicit path is used without detection (e.g. tests/mocks)."""
        import os
        import tempfile
        from nmap_scanner import NmapScanner

        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "does_not_exist_nmap.exe")
            with self.assertRaises(RuntimeError) as ctx:
                NmapScanner(nmap_path=missing)
            self.assertIn("not installed or not in PATH", str(ctx.exception))


class TestVoiceSummary(unittest.TestCase):
    """Tests for voice summary generation."""
    
    def test_voice_safe(self):
        """Test voice summary for safe results."""
        from nmap_scanner import get_voice_summary
        analysis = {"verdict": "Safe", "total_score": 0, "hosts_analyzed": 1}
        summary = get_voice_summary(analysis)
        self.assertIn("secure", summary.lower())
    
    def test_voice_critical(self):
        """Test voice summary for critical results."""
        from nmap_scanner import get_voice_summary
        analysis = {"verdict": "Critical", "total_score": 8, "hosts_analyzed": 3}
        summary = get_voice_summary(analysis)
        self.assertIn("critical", summary.lower())


if __name__ == "__main__":
    unittest.main()