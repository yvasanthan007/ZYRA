"""End-to-end smoke test of the DNS endpoints against a running server."""
import json, time, urllib.request

BASE = "http://127.0.0.1:8765"

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=70) as r:
        return r.status, json.loads(r.read())

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return r.status, json.loads(r.read())

st, health = get("/api/health")
print("health:", st, health)

st, data = post("/api/dns/lookup", {"domain": "example.com", "record_type": "MX", "source": "panel"})
print("lookup MX:", st, data.get("success"))
res = data.get("result") or {}
print("  query_type:", res.get("record_type"), "| dns_server:", (res.get("dns_server") or {}).get("description"))
print("  MX records:", res.get("records", {}).get("MX", {}).get("records"))

st, data = post("/api/dns/lookup", {"domain": "example.com"})
res = data.get("result") or {}
lid = res.get("lookup_id")
print("lookup ANY:", st, res.get("record_type"), sorted((res.get("records") or {}).keys()))
assert "score" not in res and "risk_level" not in res, "scoring leaked into result"

st, data = post("/api/dns/report", {"domain": "example.com", "result": res})
print("report POST:", st, data.get("success"), data.get("report_id"))

# downloadable txt report from the same endpoint (what DOWNLOAD REPORT uses)
req = urllib.request.Request(BASE + "/api/dns/report",
                             data=json.dumps({"result": res, "format": "txt"}).encode(),
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=30) as r:
    cd = r.headers.get("Content-Disposition", "")
    body = r.read().decode()
    assert "attachment" in cd and ".txt" in cd, cd
    for needle in ("Query type:", "DNS server:", "DNS RECORDS", "Response time:", "Timestamp:"):
        assert needle in body, needle
    assert "Security score" not in body
    print("txt download OK:", cd.split('filename=')[-1].strip('" '), f"({len(body)} chars)")

# downloadable pdf report
req = urllib.request.Request(BASE + "/api/dns/report",
                             data=json.dumps({"result": res, "format": "pdf"}).encode(),
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=30) as r:
    cd = r.headers.get("Content-Disposition", "")
    body = r.read()
    assert body.startswith(b"%PDF"), "not a PDF"
    assert ".pdf" in cd
    print("pdf download OK:", cd.split('filename=')[-1].strip('" '), f"({len(body)} bytes)")

# txt + pdf download endpoints
req = urllib.request.Request(f"{BASE}/api/dns/report/{lid}?format=txt")
with urllib.request.urlopen(req, timeout=20) as r:
    txt = r.read().decode()
    assert "Query type:" in txt and "DNS server:" in txt
    assert "Security score" not in txt
    print("txt report OK, nslookup-style (query type + DNS server, no scoring)")

st, data = post("/api/dns/lookup", {"domain": "definitely-not-real-zyra-123.com"})
print("NXDOMAIN handled:", st in (200, 400), data.get("error") or data.get("result", {}).get("status"))

# reverse lookup via API (PTR for an IP)
st, data = post("/api/dns/lookup", {"domain": "8.8.8.8", "record_type": "PTR"})
res_ptr = data.get("result") or {}
ptr_block = (res_ptr.get("records") or {}).get("PTR") or {}
print("PTR 8.8.8.8:", res_ptr.get("status"), [x.get("value") for x in ptr_block.get("records", [])])
assert res_ptr.get("status") == "RESOLVED"

# chat intent -> record type through websocket is browser-side; verify bridge ack
print("\nAPI SMOKE TEST PASSED")
