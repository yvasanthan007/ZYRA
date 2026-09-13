"""Scratch: start the ZYRA backend for e2e testing (no browser popup)."""
from backend.server import run_server

run_server(host="127.0.0.1", port=8080, open_browser=False)
