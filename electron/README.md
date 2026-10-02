# ZYRA Desktop (Electron)

Electron shell around the **existing** ZYRA web app. Nothing is rebuilt —
the FastAPI backend (`backend/server.py`) + holographic dashboard
(`desktop-dashboard/index.html`) run unchanged inside a frameless window
with a custom `ZYRA ─ □ ×` title bar.

## Run

```bash
npm install
npm run web:server   # terminal 1: existing FastAPI backend on :8080
npm run desktop      # terminal 2: Electron shell (attaches to :8080)
```

Or one command for both:

```bash
npm run dev
```

Other scripts:

| Script | Purpose |
|---|---|
| `npm run web` | legacy `python start_zyra.py` flow (unchanged) |
| `npm run web:server` | backend only (FastAPI :8080) |
| `npm run desktop` / `desktop:dev` | Electron shell (needs backend up) |
| `npm run verify` | offscreen checks: backend, dashboard, IPC, title bar |
| `npm run pack` | unpacked win dir (fast smoke test, no installer) |
| `npm run dist` | **Windows installer → `installer-output/ZYRA Setup.exe`** |

## Layout

| File | Role |
|---|---|
| `electron/main.js` | frameless `BrowserWindow` 1400×900 (min 1000×650), secure prefs |
| `electron/preload.js` | whitelisted `window.zyraAPI` only (no node/fs leak) |
| `electron/backend-manager.js` | dev: attach to :8080 · prod: spawn bundled sidecar |
| `electron/window-state.js` | remembers size/maximized in `userData` |
| `electron/window-controls.js` | min / max-toggle / restore / close IPC |
| `electron/titlebar/*` | custom title bar, injected at runtime (dashboard untouched) |
| `electron/services/*` | future-ready proxies → existing `/api/system|nmap|dns` |
| `electron/verify*.js` | offscreen verification harness |

## Notes

- Prod spawns `resources/backend/ZYRA-backend.exe` if present, else
  `python -m uvicorn backend.server:app` from bundled sources.
- External (non-127.0.0.1) links open in the OS browser.
- Backend/frontend bugs should be fixed in `backend/` + `desktop-dashboard/`,
  not in `electron/` — this layer is presentation + packaging only.
