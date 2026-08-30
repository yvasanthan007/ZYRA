"""WS test v2: longer recv timeout to catch the COMPLETE broadcast."""
import asyncio, json, time, urllib.request
import websockets

BASE = "http://127.0.0.1:8080"

async def run():
    msgs = []
    async with websockets.connect("ws://127.0.0.1:8080/ws") as ws:
        req = urllib.request.Request(BASE + "/api/url/analyze",
            data=json.dumps({"url": "https://example.com", "source": "panel"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            start = json.loads(r.read().decode())
        print("scan started:", start["scan_id"])

        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                d = json.loads(raw)
                if d.get("type", "").startswith("url"):
                    s = d.get("data") or {}
                    msgs.append({
                        "type": d.get("type"),
                        "status": s.get("status"),
                        "stage": s.get("stage"),
                        "has_result": "result" in s,
                        "score": (s.get("result") or {}).get("score") if "result" in s else None,
                    })
                    if s.get("status") == "COMPLETE":
                        print("GOT COMPLETE!")
                        break
            except asyncio.TimeoutError:
                continue
    print(f"captured {len(msgs)} url messages")
    for m in msgs[-5:]:
        print("  ", m)

asyncio.run(run())
