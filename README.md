# ZYRA AI Assistant

An intelligent voice-controlled AI assistant with a holographic dashboard, featuring link security analysis and system control capabilities.

## Features

- 🎤 **Voice Commands**: Control your PC with natural language voice commands
- 🌐 **Holographic Dashboard**: Beautiful Three.js-powered dashboard UI
- 🔒 **Link Security Analysis**: Backend-only phishing and malware detection
- 🤖 **AI Chat**: Powered by Ollama (Llama3) for intelligent conversations
- ⚡ **System Control**: Open apps, search the web, control system settings
- 💾 **Memory**: Remembers your preferences and information

## Quick Start

### Prerequisites

1. **Python 3.8+** installed
2. **Ollama** installed and running with Llama3 model
   - Download from: https://ollama.ai
   - Run: `ollama pull llama3`
3. **Microsoft Edge** browser (optional, for kiosk mode)
4. **Microphone** for voice commands

### Installation

```bash
# Install all dependencies
pip install -r requirements.txt
```

### Running ZYRA

Simply run:

```bash
python main.py
```

Or use the startup script:

```bash
python start_zyra.py
```

## What Gets Fixed

### 1. **Dashboard & WebSocket Connection**
- ✅ Improved WebSocket error handling with automatic reconnection
- ✅ Better connection status messages
- ✅ Graceful fallback when server is not ready
- ✅ Fixed WebSocket URL construction

### 2. **Voice Command System**
- ✅ Enhanced error handling in `listen.py` for microphone issues
- ✅ Improved TTS (Text-to-Speech) in `speak.py`:
  - Uses temporary files to avoid conflicts
  - Better event loop handling
  - Graceful fallback if TTS fails
- ✅ Added comprehensive error messages for speech recognition failures

### 3. **Phishing/Link Security Feature**
- ✅ **Backend-only analysis**: Never modifies frontend UI
- ✅ **Dual implementation**:
  - `backend/link_security.py` - New comprehensive security module
  - `link_analysis.py` - Legacy module with OCR support
- ✅ **Voice commands supported**:
  - "Analyze the link [URL]"
  - "Check this URL"
  - "Is this link safe?"
- ✅ **Structured reports** with:
  - Verdict (SAFE/SUSPICIOUS/PHISHING DETECTED)
  - Risk Score (Low/Medium/High/Critical)
  - Key Observations
  - Recommendations
- ✅ **Detection capabilities**:
  - Typosquatting (e.g., paypa1.com, gooogle.com)
  - Brand spoofing
  - Suspicious TLDs (.xyz, .tk, .ml, etc.)
  - IP-based hosts
  - URL shorteners
  - Encoded characters obfuscation
  - Urgency/manipulation keywords
  - Optional VirusTotal API integration

### 4. **AI Brain (brain.py)**
- ✅ Better error handling for Ollama connection issues
- ✅ Input validation
- ✅ Clear error messages when AI is unavailable
- ✅ Security persona injection to prevent LLM from fabricating link analyses
- ✅ **Thread-safe conversations** — voice loop, web API and desktop bridge can chat concurrently without corrupting context
- ✅ **Automatic model discovery** — picks the configured Ollama model or falls back to any installed one instead of hard-failing on "llama3"
- ✅ **Instruct-capable model preferred** — defaults to `phi3` (3.8B). Do *not* point
  Zyra at `tinyllama` (1.1B): it cannot hold an instruction and answers "Hii" with
  *"Sure, here's a revised version of the text ... You are Zyra, a helpful,
  intelligent AI assistant"* — it rewrites the system prompt instead of replying,
  which makes chat look broken. `llama3` (8B) also works but is slower to load.
  Override with `ZYRA_OLLAMA_MODEL` (e.g. `ZYRA_OLLAMA_MODEL=llama3`).
- ✅ **Startup warm-up** — the server and the voice loop both pre-load the model and
  pre-fill the system prompt into Ollama's KV cache in the background, so the first
  message answers in ~2s instead of ~15-20s (CPU-only machines pay the model load
  and prompt prefill on the first request otherwise)
- ✅ **Long-term memory integration** — remembered facts are injected into every prompt so Zyra answers from what she knows
- ✅ **Configurable via environment variables**:
  - `ZYRA_OLLAMA_MODEL`, `ZYRA_OLLAMA_HOST`
  - `ZYRA_AI_TEMPERATURE`, `ZYRA_AI_NUM_PREDICT`
  - `ZYRA_AI_MAX_HISTORY`, `ZYRA_AI_TIMEOUT_SECONDS`
  - `ZYRA_AI_RESPONSE_BUDGET_SECONDS` (hard reply deadline, default 120s so a
    slow CPU model is never cut off mid-answer), `ZYRA_AI_KEEP_ALIVE`
    (keeps the model warm so replies stay fast)
  - `ZYRA_AI_MAX_RESPONSE_CHARS`, `ZYRA_AI_MEMORY`
- ✅ **Retry with backoff** for transient Ollama failures + response hardening (ANSI/control chars stripped, capped length)
- ✅ **Realistic reply window** — the old 10s cut-off made slow CPU replies time out ("Ollama is not working"); the budget is now 120s (env-tunable) and the REST `/api/chat` call runs in a worker thread so a long answer never freezes the dashboard


### 5. **Main Application (main.py)**
- ✅ Fixed import inconsistencies
- ✅ Unified link analysis using `analyze_link_request()`
- ✅ Better integration between voice commands and backend security
- ✅ Improved cleanup and shutdown handling
- ✅ Signal handlers for graceful exit (Ctrl+C)

### 6. **Backend Server (backend/server.py)**
- ✅ RESTful API endpoints for all features
- ✅ WebSocket support for real-time communication
- ✅ CORS middleware for cross-origin requests
- ✅ Health check endpoint
- ✅ Link analysis API endpoint

### 7. **Bridge Module (backend/zyra_bridge.py)**
- ✅ Unified message processing
- ✅ Command mapping for all voice commands
- ✅ Backend-only link security integration
- ✅ Memory (remember/recall) support
- ✅ Text-to-speech integration

### 8. **Memory Store (memory.py)**
- ✅ **Atomic writes** — temp-file + os.replace, no more corrupted JSON on crash
- ✅ **Thread-safe** read-modify-write (concurrent remember/recall from all modules)
- ✅ **Self-healing** — damaged store is backed up and recovered automatically
- ✅ **Path resilient** — resolves memory/data.json from the module location (works from any working directory)
- ✅ Extended API: forget(), remember_many(), all_memory(), clear_memory(), stats()

## Voice Commands

### System Control
- "Open Chrome/VSCode/Notepad/Calculator/etc."
- "Close [app name]"
- "Search Google for [query]"
- "Search YouTube for [query]"
- "Shutdown/Restart/Sleep/Lock PC"
- "Take screenshot"
- "Volume up/down/mute"
- "Turn on/off WiFi"
- "Empty recycle bin"
- "What is the time/date"

### Navigation
- "Open Google/YouTube/GitHub/ChatGPT/Gmail/etc."
- "Open Downloads/Documents/Desktop"
- "Play music"
- "Open camera"

### AI Chat
- Just ask anything! ZYRA uses Llama3 for intelligent responses

### Link Security
- "Analyze the link [URL]"
- "Check this URL: [URL]"
- "Is this link safe? [URL]"
- "Analyze the link on my screen" (uses OCR)

### Memory
- "My favorite language is [language]"
- "What is my favorite language?"

### Dashboard
- "Open dashboard"
- "Show dashboard"

## Architecture

```
main.py                 # Entry point - voice loop + server startup
├── listen.py           # Speech recognition (Google Speech API)
├── speak.py            # Text-to-speech (Edge TTS)
├── brain.py            # AI brain (Ollama + Llama3)
├── memory.py           # Persistent memory (JSON)
├── commands/           # System control commands
│   ├── open_app.py    # Open applications
│   └── close_app.py   # Close applications
├── backend/            # FastAPI backend
│   ├── server.py      # REST API + WebSocket server
│   ├── zyra_bridge.py # Bridge between backend and Zyra modules
│   └── link_security.py # Link security analysis (backend-only)
├── link_analysis.py    # Legacy link analysis with OCR
├── desktop-dashboard/  # HTML dashboard (Three.js)
├── desktop-ui/         # Electron desktop shell (see "Windows Desktop Application")
├── zyra_paths.py       # Read-only resources vs. writable data paths
└── zyra.spec           # PyInstaller recipe for the bundled backend
```

## API Endpoints

### REST API
- `GET /` - Dashboard HTML
- `GET /api/health` - Health check
- `POST /api/chat` - Send chat message
- `POST /api/command` - Execute command
- `POST /api/voice` - Process voice command
- `POST /api/speak` - Text-to-speech
- `POST /api/analyze-link` - Analyze URL security
- `GET /api/commands` - List all commands

### WebSocket
- `WS /ws` - Real-time communication
  - Message types: `chat`, `command`, `voice`, `speak`, `remember`, `recall`, `analyze_link`

## Link Security Analysis

The phishing detection system works entirely in the backend and never modifies the frontend UI.

### Analysis Checklist
1. **Domain & Structure**
   - Typosquatting detection (paypaI.com, g00gle.com)
   - Excessive subdomains
   - High-risk TLDs (.xyz, .tk, .ml, etc.)
   - Raw IP addresses

2. **Protocol & Security**
   - HTTP vs HTTPS detection
   - Sensitive page detection (login, password, etc.)

3. **Obfuscation & Redirects**
   - URL shorteners (bit.ly, tinyurl, etc.)
   - '@' symbol redirects
   - Percent-encoding obfuscation
   - Punycode homograph attacks

4. **Context & Intent**
   - Urgency keywords (verify-account, urgent-action, etc.)
   - Manipulation patterns

### Example Report
```
Verdict: PHISHING DETECTED
Risk Score: High

Key Observations:
• Domain 'paypa1.com' contacted over HTTPS (scheme not specified — HTTPS assumed)
• Possible typosquatting: 'paypa1.com' imitates PayPal (paypal.com) — a classic credential-theft pattern.
• High-risk top-level domain '.com' — heavily abused in phishing and malware campaigns.

Recommendation:
Do not click or enter credentials — close the page and report the source of this link.
```

## Troubleshooting

### Voice not working?
- Check microphone permissions
- Ensure PyAudio is installed: `pip install pyaudio`
- Check internet connection (uses Google Speech API)

### AI not responding?
- Make sure Ollama is running: `ollama serve`
- Pull the Llama3 model: `ollama pull llama3`
- Slow replies are normal on CPU: a short `phi3` answer takes ~10s and `llama3`
  (8B) can take 30s+. Zyra waits up to `ZYRA_AI_RESPONSE_BUDGET_SECONDS`
  (default 120s) before giving up, so raise it if your machine is slower:
  `set ZYRA_AI_RESPONSE_BUDGET_SECONDS=180` (PowerShell:
  `$env:ZYRA_AI_RESPONSE_BUDGET_SECONDS=180`)
- Want faster replies? Use a smaller model — `ollama pull phi3` then set
  `ZYRA_OLLAMA_MODEL=phi3` (Zyra already prefers small models automatically
  and keeps the chosen one warm with `ZYRA_AI_KEEP_ALIVE=30m`)

### Dashboard not loading?
- Check if backend server started (look for "Dashboard will be available at: http://127.0.0.1:8080")
- Open browser manually at http://127.0.0.1:8080
- Check firewall settings

### Link analysis not working?
- Ensure you're using the updated `backend/link_security.py`
- Check console output for analysis results
- Voice summary requires URL in the command
- If VirusTotal checks are skipped, set `VIRUSTOTAL_API_KEY` (see below)

## VirusTotal & ML Phishing Detection Setup

All phishing detection runs in the backend and is used by **both** the voice
"Link analysis" feature (`link_analysis.py`) and the dashboard **URL Analyzer**
(`backend/url_analyzer/`), through one shared client (`backend/threat_intel.py`).

### 1. Connect VirusTotal (optional but recommended)
1. Get a free API key: https://www.virustotal.com/gui/my-apikey
2. Copy `.env.example` to `.env` and set:
   ```
   VIRUSTOTAL_API_KEY=your_key_here
   ```
   (Or set the environment variable directly.) The key is read at runtime and
   is never sent to the frontend or hard-coded.
3. Verify connectivity:
   - CLI/console: the startup banner prints `VirusTotal: connected` /
     `not configured`.
   - API: `GET /api/threat-intel/status`
     → `{"configured": true, "reachable": true, ...}`

When configured, unknown URLs are submitted to VirusTotal and the analysis is
polled to completion, so brand-new phishing URLs are actually scanned (instead
of being reported as "Unknown" or silently treated as safe).

### 2. XGBoost URL phishing analysis (local, offline)
The React link dashboard submits the exact typed URL to `POST /api/ml/phishing`;
its explicit screen-capture action gets a fresh URL from screen OCR/browser
address-bar extraction and then submits that exact result. Legacy bridge link
checks and voice URL analysis use the same XGBoost model. Failed capture or
model/API requests are reported as unverified, never safe.

- Train / retrain (deterministic seed corpus by default): `python -m backend.ml_phishing.train`
- Train from a labeled `url,label` CSV: `python -m backend.ml_phishing.train --csv dataset.csv`
- Model metadata and held-out metrics: `GET /api/ml/phishing/model`
- Instant ML check: `POST /api/ml/phishing` `{"url": "..."}`
- Searchable dataset: `GET /api/ml/phishing/dataset?search=&label=all&split=test&page=1&page_size=25`
- Disable at runtime: `ZYRA_ML_DISABLE=1`

The default builtin corpus consists of generated seed patterns, **not real-world
labeled URLs**. XGBoost probabilities are uncalibrated model outputs, not
verified real-world risk estimates. Training uses host-grouped train/validation/
test partitions; only train rows fit the model, validation selects it, and the
test rows are reported once as held-out evaluation. The React link dashboard
shows risk score, exact features, native XGBoost TreeSHAP contributions and
global feature importance separately. Per-URL contributions explain model
behavior; they do not prove maliciousness. Voice retains its existing spoken
URL-analysis response path.

## Development

### Project Structure
- All voice commands are in `commands/` directory
- Backend API in `backend/server.py`
- Bridge logic in `backend/zyra_bridge.py`
- Security analysis in `backend/link_security.py`
- Dashboard UI in `desktop-dashboard/index.html`
- Electron desktop shell in `desktop-ui/src/` (see the desktop section below)

### Adding New Commands
1. Add function in `commands/open_app.py` or `commands/close_app.py`
2. Import in `main.py`
3. Add elif clause in the main loop
4. Add to `COMMAND_MAP` in `backend/zyra_bridge.py`

## License

MIT License - Feel free to modify and use!

## Credits

- **ZYRA** - AI Assistant by Vasanthan Y
- **Ollama** - LLM runtime
- **Edge TTS** - Text-to-speech
- **Three.js** - 3D graphics
- **FastAPI** - Backend framework
## Windows Desktop Application (Electron)

ZYRA ships as a standalone Windows desktop application. The Electron shell owns
the window, the splash screen and the Python backend lifecycle; the interface
you see inside it is the existing Three.js holographic dashboard, served by the
local FastAPI backend. Nothing about the dashboard is re-implemented — the shell
loads `http://127.0.0.1:8080`, exactly the page the browser used to open.

```
Electron (ZYRA.exe)
  └── main process (desktop-ui/src/main/main.ts)
        ├── splash screen (renderer/splash.html) until /api/health answers
        ├── BackendService ── spawns ──> ZYRA-backend.exe  (or .venv python main.py)
        └── BrowserWindow ── loads ──>  http://127.0.0.1:8080  (FastAPI dashboard)
```

### Desktop components

| File | Responsibility |
| --- | --- |
| `desktop-ui/src/main/main.ts` | Window creation, lifecycle, menu, IPC handlers, security policy |
| `desktop-ui/src/main/backend-service.ts` | Backend discovery/spawn, health polling, retry, shutdown |
| `desktop-ui/src/main/zyra-paths.ts` | Resolves the project root, Python interpreter and packaged backend |
| `desktop-ui/src/main/preload.ts` | `contextBridge` surface (`window.zyraAPI`) — the only renderer↔main channel |
| `desktop-ui/src/main/python-bridge.ts` | Lazily started legacy `bridge_server.py` fallback for voice capture |
| `desktop-ui/src/renderer/` | Splash screen + the optional React desktop UI window |
| `zyra.spec` | PyInstaller recipe for the bundled Python backend |
| `tools/build_installer.ps1` | One-command build: PyInstaller → webpack → NSIS installer |
| `zyra_paths.py` | Read-only resource vs. writable data separation (Python side) |

### Backend lifecycle

1. On launch Electron probes `GET /api/health` on port **8080**.
2. If a ZYRA backend already answers (`{"zyra": "running"}`) it is **adopted** —
   no second process is started and Electron never terminates it.
3. If the port is held by some *other* service, startup fails with a clear
   message instead of adopting the wrong server.
4. Otherwise Electron spawns the backend with `ZYRA_NO_EDGE=1`, so `main.py`
   starts the FastAPI server and voice loop **without** opening the Edge kiosk
   window, and polls `/api/health` for up to 45 s.
5. When the backend is ready the splash screen is replaced by the dashboard.
6. On quit, only the process Electron spawned is terminated (the whole process
   tree, so `uvicorn` is never orphaned).

Failures are shown in the splash screen with the backend's recent output and a
**Retry backend startup** button (IPC `backend:restart`).

### Development mode

Prerequisites:

- Python 3.10+ with `pip install -r requirements.txt`
- Node.js 18+ with `cd desktop-ui; npm install`
- The project virtualenv at `.venv/` (the shell prefers it over PATH Python)

```bash
# 1. Build the Electron bundles (main, preload, renderer)
cd desktop-ui
npm run build

# 2. Launch the desktop app against the source checkout
npm start
```

`npm start` rebuilds and runs Electron. Electron starts `.venv\Scripts\python.exe
main.py` itself — do **not** start `main.py` separately.

Useful flags / environment variables:

| Variable | Effect |
| --- | --- |
| `ZYRA_PYTHON` | Explicit interpreter path (skips venv detection) |
| `ZYRA_BACKEND` | Explicit backend executable (skips all other detection) |
| `ZYRA_DATA_DIR` | Override the writable data directory |
| `electron . --desktop-ui` | Also open the legacy React desktop UI window |

You can still run the classic Python-only workflow (`python main.py`); in a
source checkout it keeps opening the Edge kiosk dashboard unless `ZYRA_NO_EDGE=1`
is set.

### Packaging the backend (PyInstaller)

```powershell
.venv\Scripts\python.exe -m PyInstaller zyra.spec --noconfirm --clean
```

Produces `dist\ZYRA-backend\ZYRA-backend.exe` plus `_internal\` containing the
dashboard, the XGBoost phishing model, EasyOCR weights and Torch/Torchvision
DLLs. The result needs no Python installation on the target machine.

### Building the Windows installer

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_installer.ps1
```

The script runs PyInstaller, then `npm run build` (webpack main + preload +
renderer), then electron-builder with the NSIS target. Options: `-BackendOnly`,
`-SkipBackend`, `-SkipWebpack`.

Output:

```
dist/ZYRA-backend/                            # self-contained Python backend
desktop-ui/dist/                              # webpack bundles
desktop-ui/release/win-unpacked/ZYRA.exe      # unpacked application
desktop-ui/release/ZYRA-Setup-<version>.exe   # NSIS installer
```

The installer creates Desktop and Start-menu shortcuts, lets the user choose
the install directory, and reuses the ZYRA icon (`desktop-ui/build-assets/icon.ico`)
for the window, the executable, the installer and the shortcuts.

### Packaged resource layout

```
ZYRA/                     (install directory)
└── resources/
    ├── app.asar          Electron code (dist/ + package.json)
    └── zyra/
        ├── ZYRA-backend.exe
        └── _internal/
            ├── desktop-dashboard/          # evaluated read-only
            └── backend/ml_phishing/models/phishing_model.joblib
```

### Writable data location

Packaged builds never write next to the executable. All runtime data goes to:

```
%LOCALAPPDATA%\ZYRA\data\
```

which includes `memory/data.json`, `url_scan_history.json`,
`dns_lookup_history.json`, `nmap/*.xml` and `ml_phishing/live_analysis.jsonl`.
Set `ZYRA_DATA_DIR` to relocate it. In a source checkout the project root is
still used, so the development layout is unchanged.

### Desktop troubleshooting

- **"Port 8080 is in use by a service that is not the ZYRA backend."** Another
  program owns the port. Close it (or stop the stray `python main.py`) and press
  *Retry backend startup*.
- **"The ZYRA backend did not become ready…"** The splash screen shows the last
  backend lines. In development, check `npm start` output for Python import
  errors; in a packaged build, reinstall.
- **No Edge window appears.** Expected: desktop mode sets `ZYRA_NO_EDGE=1`.
- **Model/OCR unavailable in the packaged build.** Rebuild with
  `.venv\Scripts\python.exe -m PyInstaller zyra.spec --clean`, and make sure the
  EasyOCR cache exists under `%USERPROFILE%\.EasyOCR\model` before packing.
- **Orphaned backend after a crash.** Conflict with a hard kill; normally the
  process tree is reaped. If needed, end `ZYRA-backend.exe` in Task Manager.
