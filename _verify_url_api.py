"""Quick verification of the URL Analyzer API endpoints."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8123"
URL = "https://example.com"


def get(path, timeout=15):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "zyra-verify"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def post(path, payload, timeout=60):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout).read()


print("1) history endpoint:")
try:
    raw = get("/api/url/history", timeout=10).decode()
    print("   OK:", raw[:160])
except Exception as e:
    print("   ERR:", e)

print("\n2) analyze endpoint:")
try:
    raw = post("/api/url/analyze", {"url": URL}, timeout=60).decode()
    data = json.loads(raw)
    print("   success:", data.get("success"))
    res = data.get("result", {})
    print("   scan_id:", res.get("scan_id"))
    print("   score:", res.get("score"), "risk:", res.get("risk_level"),
          "class:", res.get("classification"))
    sid = res.get("scan_id")
except Exception as e:
    print("   ERR:", e)
    sid = None

if sid:
    print("\n3) report JSON:")
    try:
        raw = get(f"/api/url/report/{sid}?format=json", timeout=15).decode()
        print("   OK:", raw[:160])
    except Exception as e:
        print("   ERR:", e)
    print("\n4) report TXT:")
    try:
        raw = get(f"/api/url/report/{sid}?format=txt", timeout=15).decode()
        print("   OK head:", raw[:120].replace("\n", " | "))
    except Exception as e:
        print("   ERR:", e)
    print("\n5) report PDF:")
    try:
        raw = get(f"/api/url/report/{sid}?format=pdf", timeout=30)
        print("   PDF bytes:", len(raw), "header:", raw[:8])
    except Exception as e:
        print("   ERR:", e)

print("\nDONE")
