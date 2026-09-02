"""Quick verification of the DNS lookup additions (nslookup-style, no scoring)."""
from backend.dns_lookup import (
    query_single, get_dns_server_info, extract_dns_record_type,
    run_dns_lookup, extract_dns_target, is_dns_intent,
)

print("import OK")
info = get_dns_server_info()
print("DNS server info:", info)
assert info["nameservers"], "expected system nameservers"

print("record type extract:", extract_dns_record_type("check MX record for example.com"))
assert extract_dns_record_type("check MX record for example.com") == "MX"
print("target extract:", extract_dns_target("Run nslookup for example.com"))
assert extract_dns_target("Run nslookup for example.com") == "example.com"
assert is_dns_intent("DNS lookup example.com")
assert is_dns_intent("Reverse lookup 8.8.8.8")

# single-type queries (real DNS)
r = query_single("example.com", "MX")
print("MX single:", r["block"]["status"], r["block"]["records"][:2])

r = query_single("example.com", "A")
print("A single:", r["block"]["status"], [x["value"] for x in r["block"]["records"]])

# reverse lookup for a real IP
r = query_single("8.8.8.8", "PTR")
print("PTR 8.8.8.8:", r["block"]["status"], [x["value"] for x in r["block"]["records"]])
assert r["block"]["status"] == "OK"

# full pipeline with a record-type filter
res = run_dns_lookup("example.com", lookup_id="dns_verify_test", record_type="MX")
print("filtered records keys:", list(res["records"].keys()))
assert list(res["records"].keys()) == ["MX"]
assert res["record_type"] == "MX"
assert res["dns_server"]["nameservers"]
# nslookup-style: no security scoring anywhere
for banned in ("score", "risk_level", "findings", "warnings", "recommendations"):
    assert banned not in res, f"scoring field {banned} still present"

res2 = run_dns_lookup("example.com", lookup_id="dns_verify_any")
print("ANY keys:", sorted(res2["records"].keys()))

# error handling: NXDOMAIN
res3 = run_dns_lookup("this-domain-does-not-exist-zyra-xyz.com", lookup_id="dns_verify_nx")
print("NXDOMAIN ->", res3.get("status"), res3.get("resolution", {}).get("error"))

from backend.dns_lookup.report import build_report_data, report_to_text
rep = build_report_data(res)
txt = report_to_text(rep)
assert "Query type:" in txt and "DNS server:" in txt
assert "Security score" not in txt and "Risk level" not in txt
print("report text is nslookup-style: OK")
print(build_dns_report_text_preview := txt[:600])
print("\nALL CHECKS PASSED")
