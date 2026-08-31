"""Package-level test for backend.dns_lookup (pipeline + scorer + intent + report)."""
import json

from backend.dns_lookup import (
    DNS_STAGES,
    build_dns_report_data,
    build_voice_summary,
    dns_report_filename,
    dns_report_to_pdf,
    dns_report_to_text,
    extract_dns_target,
    is_dns_intent,
    run_dns_lookup,
    validate_domain,
)

# ── Intent detection ──
cases = [
    ("Analyze DNS of example.com", True),
    ("DNS lookup for example.com", True),
    ("Check MX records for example.com", True),
    ("what nameservers does github.com use", True),
    ("nslookup google.com", True),
    ("check spf record for example.com", True),
    ("reverse dns for 8.8.8.8", True),
    ("open chrome", False),
    ("scan my network", False),
    ("analyze https://example.com for threats", False),  # URL intent, not DNS
    ("what is the weather", False),
]
print("── intent ──")
for text, expected in cases:
    got = is_dns_intent(text)
    mark = "OK " if got == expected else "FAIL"
    print(f"  [{mark}] is_dns_intent({text!r}) = {got} (want {expected})")

targets = [
    ("Check MX records for gmail.com", "gmail.com"),
    ("Analyze DNS of www.example.com", "www.example.com"),
    ("reverse dns for 8.8.8.8", "8.8.8.8"),
    ("https://www.google.com/search?q=dns", "www.google.com"),
]
print("── target extraction ──")
for text, expected in targets:
    got = extract_dns_target(text)
    mark = "OK " if got == expected else "FAIL"
    print(f"  [{mark}] extract({text!r}) = {got!r} (want {expected!r})")

# ── Validator ──
print("── validator ──")
for bad in ("", "localhost", "127.0.0.1", "example.com; rm -rf /", "a" * 300,
            "example.invalid..", "under_score.example.com", "192.168.1.1"):
    try:
        validate_domain(bad)
        print(f"  [FAIL] {bad!r} accepted (should reject)")
    except Exception as e:
        print(f"  [OK ] {bad!r} rejected: {str(e)[:60]}")
good = validate_domain("https://www.Example.com/path?q=1")
print(f"  [OK ] URL stripped -> {good['domain']}")

# ── Full pipeline (real DNS) ──
print("── pipeline: example.com ──")
stages_seen = []
result = run_dns_lookup("example.com", source="test",
                        on_stage=lambda u, s: stages_seen.append(u["stage"]))
print("  stages seen:", stages_seen)
print("  success:", result["success"], "| status:", result["status"],
      "| score:", result["score"], "| risk:", result["risk_level"])
print("  response_time_ms:", result["response_time_ms"], "| total:", result["total_time_ms"])
print("  A:", [r["value"] for r in result["records"]["A"]["records"]])
print("  NS:", [r["value"] for r in result["records"]["NS"]["records"]])
print("  MX:", [r["value"] for r in result["records"]["MX"]["records"]])
print("  SOA:", [r["value"][:40] for r in result["records"]["SOA"]["records"]])
print("  DNSSEC:", result["dnssec"]["status"])
print("  findings:", [(f["severity"], f["title"]) for f in result["findings"]])
print("  warnings:", len(result["warnings"]), "| recommendations:", len(result["recommendations"]))
assert result["success"] and result["status"] == "RESOLVED" and result["score"] > 0

print("── pipeline: invalid domain ──")
r2 = run_dns_lookup("this-domain-does-not-exist-zyra-test.com", source="test")
print("  success:", r2["success"], "| error:", (r2.get("error") or "")[:60])

print("── pipeline: reserved (localhost) ──")
r3 = run_dns_lookup("localhost", source="test")
print("  success:", r3["success"], "| error:", r3.get("error"))

# ── Voice summary ──
print("── voice summary ──")
print("  ", build_voice_summary(result))
print("  ", build_voice_summary(r2))

# ── Report ──
print("── report ──")
report = build_dns_report_data(result)
txt = dns_report_to_text(report)
pdf = dns_report_to_pdf(report)
print("  filename:", dns_report_filename(result))
print("  text report:", len(txt), "chars |", txt.splitlines()[1])
print("  pdf bytes:", len(pdf), "| header:", pdf[:8])
assert pdf.startswith(b"%PDF")
print()
print("ALL PACKAGE TESTS DONE")

import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location(
    "dns_resolver", "backend/dns_lookup/resolver.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

print("=== example.com ===")
r = m.resolve_all("example.com", apex="example.com")
print("resolved:", r["resolution"]["resolved"], r["resolution"]["ips"][:2])
print("ms:", r["response_time_ms"], "total:", r["total_time_ms"])
for t in ("A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA"):
    b = r["records"].get(t, {})
    print(f"  {t}: {b.get('status')} count={b.get('count')} ttl={b.get('ttl')} err={b.get('error')}")
print("DNSSEC:", r["dnssec"]["status"], "| SPF:", r["txt_policy"]["spf"]["present"], r["txt_policy"]["spf"]["record"], "| DMARC:", r["txt_policy"]["dmarc"]["present"])
print("reverse:", r["reverse"]["any_found"], r["reverse"]["hostnames"][:1])
print("wildcard:", r["wildcard"])

print()
print("=== google.com MX ===")
r2 = m.resolve_all("google.com", apex="google.com")
print("MX:", [x["value"] for x in r2["records"]["MX"]["records"]][:3])
print("DNSSEC:", r2["dnssec"]["status"], "ad:", r2["dnssec"]["ad_flag"], "ds:", r2["dnssec"]["ds"])

print()
print("=== 8.8.8.8 (reverse IP) ===")
r3 = m.resolve_all("8.8.8.8", is_ip=True)
print("PTR:", [x["value"] for x in r3["records"]["PTR"]["records"]])
print("reverse:", r3["reverse"])

print()
print("=== nonexistent.invalid ===")
r4 = m.resolve_all("nonexistent.zyra-test-invalid-domain.com", apex="nonexistent.zyra-test-invalid-domain.com")
print("resolved:", r4["resolution"]["resolved"], "| A err:", r4["records"]["A"]["error"])

print()
print("=== www.github.com (subdomain + apex dnssec) ===")
r5 = m.resolve_all("www.github.com", apex="github.com")
print("resolved:", r5["resolution"]["resolved"], "| CNAME:", [x["value"] for x in r5["records"]["CNAME"]["records"]])
print("DNSSEC at apex github.com:", r5["dnssec"]["status"])

print()
print("ALL RESOLVER TESTS DONE")
