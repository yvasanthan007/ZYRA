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

## Nmap scans never ask for permission

Nmap's raw-socket operations (`-sS` SYN scan, `-sn` raw ping sweep, `-O` OS
detection, `-A` aggressive scan) require **Administrator rights** on Windows.
Requesting them causes the Windows admin/UAC consent prompt to appear on
**every** scan.

ZYRA avoids this completely — it never asks you to elevate:

- On startup, `nmap_scanner.has_raw_socket_privileges()` checks the process
  privileges **once** and caches the result.
- When ZYRA is **not** elevated, scans silently switch to the unprivileged
  TCP connect equivalents, which produce the same port/service/version results:

  | Requested | Runs unprivileged as |
  |---|---|
  | `-sS` SYN scan | `-sT` TCP connect scan |
  | `-sn` raw ping sweep | `-Pn -sT -p 22,80,135,443,445,3389,8080` + liveness filter |
  | `-O` / `-A` (full scan) | `-sV -sC` (version + default NSE scripts) |

- The command shown in the Nmap Scanner panel is built by the **same**
  privilege-aware builder that executes the scan, so the preview always matches
  what actually runs.
- When ZYRA **is** elevated (e.g. started from an Administrator terminal), the
  full-power `-sS` / `-O` / `-A` scans are used automatically — no config needed.
- Each scan result includes `privilege_mode` (`"privileged"` or
  `"unprivileged"`), and a note appears in **Security Observations** explaining
  any capability that was skipped automatically.

Result: scans always run unattended, with no admin prompt and no manual
permission step.

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

## Nmap scanning — never asks for permission

Nmap scans run **without any admin/UAC consent prompt**, automatically.

Raw-packet nmap features (`-sS` SYN scan, `-O` OS detection, `-A` aggressive
scan, `-sn` raw ping sweep) require Administrator rights on Windows. Requesting
them is what caused the repeated "allow this app" elevation dialog.

ZYRA now detects its privilege level **once at startup** (`has_raw_socket_privileges()`
in `nmap_scanner.py`) and silently picks the strongest scan it can run:

| When ZYRA is... | Scan used | Prompts? |
|---|---|---|
| **Not elevated** (normal) | `-sT` TCP connect scan, `-sV` version detection, `-sC` scripts; host discovery via TCP connect probes | **None** |
| **Elevated** (run as Administrator) | Original `-sS` / `-O` / `-A` / `-sn` raw scans | None (already admin) |

Key points:

- No elevation is ever requested, and no `runas`/`ShellExecute` call exists
  anywhere in the project — scanning simply degrades to the unprivileged
  equivalent instead of prompting.
- The command shown in the Nmap Scanner panel always matches what actually
  executes (both come from the same privilege-aware `build_scan_args()`).
- When a capability is skipped (e.g. OS detection without admin), a short note
  is appended to the **Security Observations** card — so the downgrade is
  visible rather than a silent surprise. All port, service and version
  detection still works.
- Trade-off: unprivileged `-sT` connect scans are slightly slower and more
  detectable than `-sS` SYN scans, and OS detection is only available when
  ZYRA runs as Administrator. This is the unavoidable cost of never asking
  for permission.

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
| `nmap_scanner.py` | privilege layer added | Detects raw-socket capability once (`has_raw_socket_privileges()`) and silently swaps `-sS`/`-O`/`-A`/`-sn` for `-sT`/`-sV`/`-sC` equivalents when unprivileged, so a scan never raises the admin prompt. `scan_host()` and `ping_sweep()` now build args through the shared `build_scan_args()` so the displayed and executed commands are identical. Scan results expose `privilege_mode`. |
| `backend/nmap_service.py` | ~27 lines added | Adds the `UNPRIVILEGED_NOTES` explanations and puts `privilege_mode` in the scan payload; appends one observation line only when a capability was auto-skipped. |
| `backend/server.py` | 6 lines added | `/api/nmap/operations` now returns `example_command` built by the privilege-aware builder, so the panel preview never shows raw-socket flags that would need admin. |
| `README-DESKTOP.md` | Nmap section added | Documents the no-permission scanning behavior. |

Everything else — backend, dashboard, voice, AI, Nmap, URL Analyzer, DNS,
memory, commands — is untouched.

