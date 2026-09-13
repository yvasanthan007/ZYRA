#!/usr/bin/env python3
"""
ZYRA Desktop — backend launcher.

Runs the EXISTING ZYRA backend server (backend/server.py) exactly as
main.py does today, but without opening a browser (the Electron desktop
window loads the dashboard instead of Edge kiosk mode).

This file does not modify any ZYRA module — it only calls the existing
`run_server()` entry point from backend/server.py.
"""
import os
import sys

# Make the ZYRA project root importable (same pattern backend/server.py uses)
ZYRA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ZYRA_ROOT not in sys.path:
    sys.path.insert(0, ZYRA_ROOT)

from backend.server import run_server  # noqa: E402

if __name__ == "__main__":
    host = os.environ.get("ZYRA_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("ZYRA_SERVER_PORT", "8080"))
    # open_browser=False: the desktop shell renders the UI, not Edge kiosk
    run_server(host=host, port=port, open_browser=False)
