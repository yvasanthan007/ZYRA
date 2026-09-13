"""Scratch: end-to-end backend connection smoke test.

Verifies the exact paths the dashboard uses:
  1. REST: dashboard HTML, health, nmap state/operations, url/dns history
  2. WebSocket chat -> response (works even when Ollama is offline)
  3. URL analyze  -> streamed url_status to completion, WS stays open after
  4. DNS lookup   -> streamed dns_status to completion

Exit code 0 = all passed.
"""
import asyncio
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8080"
WS_URL = "ws://127.0.0.1:8080/ws"
URL_TIMEOUT = 100   # watchdog allows 90s
DNS_TIMEOUT = 40

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} - {name}" + (f" :: {detail}" if detail else ""))


def rest(method, path, payload=None, timeout=15):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


async def ws_collect(ws, stop_pred, timeout_s):
    """Collect messages until stop_pred(msgs) is true or timeout."""
    msgs = []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.2, deadline - time.time()))
        except asyncio.TimeoutError:
            break
        except Exception:
            break  # connection closed or transport error
        try:
            m = json.loads(raw)
        except (ValueError, TypeError):
            continue
        msgs.append(m)
        if stop_pred(msgs):
            break
    return msgs


async def main():
    import websockets

    print("=== 1. REST checks ===")
    try:
        status, body = rest("GET", "/api/health")
        record("GET /api/health", status == 200 and body.get("status") == "ok", str(body))
    except Exception as e:
        record("GET /api/health", False, repr(e))
        return

    for path, keys in [("/api/nmap/state", ("nmap_available",)),
                       ("/api/nmap/operations", ("operations",)),
                       ("/api/url/history", ("success",)),
                       ("/api/dns/history", ("success",))]:
        try:
            status, body = rest("GET", path)
            ok = status == 200 and any(
                body.get(k) is not None or body.get("data", {}).get(k) is not None
                if isinstance(body.get("data"), dict) else body.get(k) is not None
                for k in keys)
            record(f"GET {path}", ok)
        except Exception as e:
            record(f"GET {path}", False, repr(e))

    try:
        req = urllib.request.Request(BASE + "/")
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read()
        record("GET / (dashboard HTML)", resp.status == 200 and b"ZYRA" in html,
               f"{len(html)} bytes")
    except Exception as e:
        record("GET / (dashboard HTML)", False, repr(e))

    print("=== 2. WebSocket chat ===")
    async with websockets.connect(WS_URL, open_timeout=10) as ws:
        await ws.send(json.dumps({"type": "chat", "data": "hello ZYRA"}))
        chat_msgs = await ws_collect(
            ws, lambda ms: any(m.get("type") == "response" for m in ms), 30)
        resp = next((m for m in chat_msgs if m.get("type") == "response"), None)
        record("WS chat -> response", resp is not None and resp.get("success"),
               str((resp or {}).get("data", (resp or {}).get("error", "")))[:90])

        print("=== 3. URL analyze streams to completion ===")
        status, body = rest("POST", "/api/url/analyze",
                            {"url": "https://example.com", "source": "panel"})
        record("POST /api/url/analyze", status == 200 and body.get("success"),
               f"scan_id={body.get('scan_id')}")
        scan_id = body.get("scan_id")

        url_msgs = await ws_collect(ws, lambda ms: any(
            m.get("type") == "url_status"
            and m.get("data", {}).get("status") in ("COMPLETE", "ERROR")
            for m in ms), URL_TIMEOUT)
        final = next((m for m in reversed(url_msgs)
                      if m.get("type") == "url_status"
                      and m.get("data", {}).get("status") in ("COMPLETE", "ERROR")), None)
        record("URL scan streams to COMPLETE",
               final is not None and final.get("data", {}).get("status") == "COMPLETE",
               f"stage={final.get('data', {}).get('stage') if final else None}, "
               f"messages={len(url_msgs)}")

        if final and final.get("data", {}).get("status") == "COMPLETE":
            st, rb = rest("GET", f"/api/url/result/{scan_id}")
            record("GET /api/url/result/<id>", st == 200 and rb.get("success"))

        # Regression: the old on_complete crash closed the WS right after a
        # URL scan finished. Prove the socket survives and still serves chat.
        try:
            await ws.send(json.dumps({"type": "chat", "data": "are you still there?"}))
            post_msgs = await ws_collect(
                ws, lambda ms: any(m.get("type") == "response" for m in ms), 30)
            record("WS stays open after URL scan (chat works)",
                   any(m.get("type") == "response" and m.get("success")
                       for m in post_msgs))
        except Exception as e:
            record("WS stays open after URL scan (chat works)", False,
                   f"socket closed/unusable: {e!r}")

    print("=== 4. DNS lookup streams to completion ===")
    async with websockets.connect(WS_URL, open_timeout=10) as ws:
        status, body = rest("POST", "/api/dns/lookup",
                            {"domain": "example.com", "source": "panel"})
        record("POST /api/dns/lookup", status == 200 and body.get("success"),
               f"lookup_id={body.get('lookup_id')}")

        dns_msgs = await ws_collect(ws, lambda ms: any(
            m.get("type") == "dns_status"
            and m.get("data", {}).get("status") in ("COMPLETE", "ERROR")
            for m in ms), DNS_TIMEOUT)
        dfinal = next((m for m in reversed(dns_msgs)
                       if m.get("type") == "dns_status"
                       and m.get("data", {}).get("status") in ("COMPLETE", "ERROR")), None)
        record("DNS lookup streams to COMPLETE",
               dfinal is not None and dfinal.get("data", {}).get("status") == "COMPLETE",
               f"messages={len(dns_msgs)}")

        if dfinal and dfinal.get("data", {}).get("status") == "COMPLETE":
            lid = body.get("lookup_id")
            st, rb = rest("GET", f"/api/dns/result/{lid}")
            record("GET /api/dns/result/<id>", st == 200 and rb.get("success"))

    print()
    failed = [r for r in results if not r[1]]
    print(f"RESULT: {len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", [r[0] for r in failed])
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

