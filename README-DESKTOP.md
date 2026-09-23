# ZYRA Desktop

ZYRA Desktop wraps the **existing ZYRA web application** in a native desktop
window. The Python backend, FastAPI server, dashboard UI, voice modules,
Nmap / URL Analyzer / DNS tools, memory database, and all API connections are
**100% unchanged** — the desktop shell simply replaces the
"open Microsoft Edge in kiosk mode" step.

```
ZYRA Desktop Application (Electron shell: desktop/main.js)
        │  waits for http://127.0.0.1:8080/api/health
        │  opens a native window with the existing dashboard
        │
        └── Existing ZYRA Application (unmodified)
               ├── main.py (voice loop + backend server thread)
               ├── backend/server.py (FastAPI: REST + WebSocket on 127.0.0.1:8080)
               ├── desktop-dashboard/index.html (same UI as in the browser)
               ├── backend/* (URL Analyzer, DNS, Nmap, link security)
               ├── memory/ (chat history & remembered facts)
               └── Ollama / edge-tts / mic (system services, unchanged)
```

## Running

### `python main.py` — now opens the ZYRA Desktop window (default)
```bash
python main.py
```
- Starts the existing backend exactly as before (server thread + voice loop)
- Opens the **native ZYRA Desktop window** with the dashboard instead of Edge
- Closing the window stops ZYRA (backend included) cleanly
- Ctrl+C in the console also closes the desktop window
- If the Electron shell is missing (no `node_modules/electron`), it falls
  back to the classic Edge kiosk mode automatically

### Desktop development mode (Electron-first)
```bash
npm run desktop:dev
```
- The shell spawns the project's own `.venv` Python running `main.py`
  (with `ZYRA_DESKTOP=1`) and opens the window itself
- Closing the window stops the backend process tree automatically

### Classic localhost mode (unchanged behavior)
```bash
$env:ZYRA_DESKTOP = "1"; python main.py   # server only — no window, no browser
```

## Production build (Windows)

```bash
npm run desktop:build        # -> desktop-dist/ZYRA-Setup-1.0.0.exe (installer)
npm run desktop:build:dir    # -> desktop-dist/win-unpacked/ZYRA.exe (portable)
npm run desktop:build:full   # installer that also bundles the project .venv
                             #    (fully self-contained; large, multi-GB)
```

The default build packages the Electron shell + the ZYRA source into
`resources/zyra`. At startup it looks for Python in this order:

1. `ZYRA_PYTHON` environment variable (full path to a python.exe)
2. `<install>\resources\zyra\.venv\Scripts\pythonw.exe` (bundled venv —
   created automatically by `desktop:build:full`, or copy a venv there)
3. `<install>\resources\zyra\python\pythonw.exe` (portable Python runtime)
4. The project `.venv` (development machine)
5. `python` on the system PATH (must have `pip install -r requirements.txt`)

Ollama, Nmap (`nmap.exe`), a microphone, and internet access are runtime
requirements, exactly as for the localhost version.

## Linux / macOS

The build config in `package.json` already contains `linux` (AppImage) and
`mac` (dmg) targets. Build with:

```bash
npx electron-builder --linux     # on Linux
npx electron-builder --mac       # on macOS
```

No ZYRA application code needs to change for other platforms.

## Security

- `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`
- Empty preload — **no Node APIs are exposed** to the dashboard
- Permission handler allows only `media` (microphone); everything else denied
- External links open in the system browser, never inside the shell
- Single-instance lock prevents duplicate ZYRA desktop sessions
- Backend stays bound to `127.0.0.1` only (unchanged)

## What was changed (and why)

| File | Change | Why |
|---|---|---|
| `desktop/main.js` | **new** | Electron shell: waits for backend health, loads the existing dashboard URL, supports both launch directions (shell→backend and backend→shell), kills the Python tree on window close |
| `desktop/preload.js` | **new** | Required secure preload placeholder (exposes nothing) |
| `desktop/package.json` | **new** | App manifest so Electron/electron-builder can resolve the shell |
| `desktop/builder-full.json` | **new** | Optional fully self-contained installer (bundles `.venv`) |
| `desktop/zyra.ico` | **new** | Application icon (from the existing project assets) |
| `package.json` (root) | **new** | `desktop:dev` / `desktop:build` scripts + electron-builder config |
| `main.py` | ~60 lines, isolated | 1) skip Edge launch when `ZYRA_DESKTOP=1` (Electron-first mode); 2) `open_dashboard_in_desktop_shell()` launches the native window instead of Edge by default, with Edge kept as fallback; 3) `cleanup()` also closes the window. Behavior without the Electron shell is unchanged. |
| `.gitignore` | 2 lines | Ignore `desktop/node_modules/` and `desktop-dist/` |

Everything else — backend, dashboard, voice, AI, Nmap, URL Analyzer, DNS,
memory, commands — is untouched.

