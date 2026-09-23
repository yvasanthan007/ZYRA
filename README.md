# ZYRA AI Assistant

An intelligent voice-controlled AI assistant with a holographic dashboard, featuring link security analysis and system control capabilities.

## Features

* 🎤 **Voice Commands**: Control your PC with natural language voice commands
* 🌐 **Holographic Dashboard**: Beautiful Three.js-powered dashboard UI
* 🔒 **Link Security Analysis**: Backend-only phishing and malware detection
* 🤖 **AI Chat**: Powered by Ollama (Llama3) for intelligent conversations
* ⚡ **System Control**: Open apps, search the web, control system settings
* 💾 **Memory**: Remembers your preferences and information

## Quick Start

### Prerequisites

1. **Python 3.8+** installed
2. **Ollama** installed and running with Llama3 model

   * Download from: https://ollama.ai
   * Run: `ollama pull llama3`
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

* ✅ Improved WebSocket error handling with automatic reconnection
* ✅ Better connection status messages
* ✅ Graceful fallback when server is not ready
* ✅ Fixed WebSocket URL construction

### 2. **Voice Command System**

* ✅ Enhanced error handling in `listen.py` for microphone issues
* ✅ Improved TTS (Text-to-Speech) in `speak.py`:

  * Uses temporary files to avoid conflicts
  * Better event loop handling
  * Graceful fallback if TTS fails
* ✅ Added comprehensive error messages for speech recognition failures

### 3. **Phishing/Link Security Feature**

* ✅ **Backend-only analysis**: Never modifies frontend UI
* ✅ **Dual implementation**:

  * `backend/link_security.py` - New comprehensive security module
  * `link_analysis.py` - Legacy module with OCR support
* ✅ **Voice commands supported**:

  * "Analyze the link [URL]"
  * "Check this URL"
  * "Is this link safe?"
* ✅ **Structured reports** with:

  * Verdict (SAFE/SUSPICIOUS/PHISHING DETECTED)
  * Risk Score (Low/Medium/High/Critical)
  * Key Observations
  * Recommendations
* ✅ **Detection capabilities**:

  * Typosquatting (e.g., paypa1.com, gooogle.com)
  * Brand spoofing
  * Suspicious TLDs (.xyz, .tk, .ml, etc.)
  * IP-based hosts
  * URL shorteners
  * Encoded characters obfuscation
  * Urgency/manipulation keywords
  * Optional VirusTotal API integration

### 4. **AI Brain (brain.py)**

* ✅ Better error handling for Ollama connection issues
* ✅ Input validation
* ✅ Clear error messages when AI is unavailable
* ✅ Security persona injection to prevent LLM from fabricating link analyses
* ✅ **Thread-safe conversations** — voice loop, web API and desktop bridge can chat concurrently without corrupting context
* ✅ **Automatic model discovery** — picks the configured Ollama model or falls back to any installed one instead of hard-failing on "llama3"
* ✅ **Long-term memory integration** — remembered facts are injected into every prompt so Zyra answers from what she knows
* ✅ **Configurable via environment variables**:

  * `ZYRA_OLLAMA_MODEL`, `ZYRA_OLLAMA_HOST`
  * `ZYRA_AI_TEMPERATURE`, `ZYRA_AI_NUM_PREDICT`
  * `ZYRA_AI_MAX_HISTORY`, `ZYRA_AI_TIMEOUT_SECONDS`
  * `ZYRA_AI_RESPONSE_BUDGET_SECONDS` (hard reply deadline, default 10s)
  * `ZYRA_AI_KEEP_ALIVE` (keeps the model warm so replies stay fast)
  * `ZYRA_AI_MAX_RESPONSE_CHARS`, `ZYRA_AI_MEMORY`
* ✅ **Retry with backoff** for transient Ollama failures + response hardening (ANSI/control chars stripped, capped length)

### 5. **Main Application (main.py)**

* ✅ Fixed import inconsistencies
* ✅ Unified link analysis using `analyze_link_request()`
* ✅ Better integration between voice commands and backend security
* ✅ Improved cleanup and shutdown handling
* ✅ Signal handlers for graceful exit (Ctrl+C)

### 6. **Backend Server (backend/server.py)**

* ✅ RESTful API endpoints for all features
* ✅ WebSocket support for real-time communication
* ✅ CORS middleware for cross-origin requests
* ✅ Health check endpoint
* ✅ Link analysis API endpoint

### 7. **Bridge Module (backend/zyra_bridge.py)**

* ✅ Unified message processing
* ✅ Command mapping for all voice commands
* ✅ Backend-only link security integration
* ✅ Memory (remember/recall) support
* ✅ Text-to-speech integration

### 8. **Memory Store (memory.py)**

* ✅ **Atomic writes** — temp-file + os.replace, no more corrupted JSON on crash
* ✅ **Thread-safe** read-modify-write (concurrent remember/recall from all modules)
* ✅ **Self-healing** — damaged store is backed up and recovered automatically
* ✅ **Path resilient** — resolves memory/data.json from the module location (works from any working directory)
* ✅ Extended API: forget(), remember_many(), all_memory(), clear_memory(), stats()

## Voice Commands

### System Control

* "Open Chrome/VSCode/Notepad/Calculator/etc."
* "Close [app name]"
* "Search Google for [query]"
* "Search YouTube for [query]"
* "Shutdown/Restart/Sleep/Lock PC"
* "Take screenshot"
* "Volume up/down/mute"
* "Turn on/off WiFi"
* "Empty recycle bin"
* "What is the time/date"

### Navigation

* "Open Google/YouTube/GitHub/ChatGPT/Gmail/etc."
* "Open Downloads/Documents/Desktop"
* "Play music"
* "Open camera"

### AI Chat

* Just ask anything! ZYRA uses Llama3 for intelligent responses

### Link Security

* "Analyze the link [URL]"
* "Check this URL: [URL]"
* "Is this link safe? [URL]"
* "Analyze the link on my screen" (uses OCR)

### Memory

* "My favorite language is [language]"
* "What is my favorite language?"

### Dashboard

* "Open dashboard"
* "Show dashboard"

## Architecture

```text
main.py                 # Entry point - voice loop + server startup
├── listen.py           # Speech recognition (Google Speech API)
├── speak.py            # Text-to-speech (Edge TTS)
├── brain.py            # AI brain (Ollama + Llama3)
├── memory.py           # Persistent memory (JSON)
├── commands/            # System control commands
│   ├── open_app.py     # Open applications
│   └── close_app.py    # Close applications
├── backend/             # FastAPI backend
│   ├── server.py        # REST API + WebSocket server
│   ├── zyra_bridge.py   # Bridge between backend and Zyra modules
│   └── link_security.py # Link security analysis (backend-only)
├── link_analysis.py     # Legacy link analysis with OCR
└── desktop-dashboard/   # HTML dashboard (Three.js)
```

## API Endpoints

### REST API

* `GET /` - Dashboard HTML
* `GET /api/health` - Health check
* `POST /api/chat` - Send chat message
* `POST /api/command` - Execute command
* `POST /api/voice` - Process voice command
* `POST /api/speak` - Text-to-speech
* `POST /api/analyze-link` - Analyze URL security
* `GET /api/commands` - List all commands

### WebSocket

* `WS /ws` - Real-time communication

  * Message types: `chat`, `command`, `voice`, `speak`, `remember`, `recall`, `analyze_link`

## Link Security Analysis

The phishing detection system works entirely in the backend and never modifies the frontend UI.

### Analysis Checklist

1. **Domain & Structure**

   * Typosquatting detection (paypaI.com, g00gle.com)
   * Excessive subdomains
   * High-risk TLDs (.xyz, .tk, .ml, etc.)
   * Raw IP addresses

2. **Protocol & Security**

   * HTTP vs HTTPS detection
   * Sensitive page detection (login, password, etc.)

3. **Obfuscation & Redirects**

   * URL shorteners (bit.ly, tinyurl, etc.)
   * '@' symbol redirects
   * Percent-encoding obfuscation
   * Punycode homograph attacks

4. **Context & Intent**

   * Urgency keywords (verify-account, urgent-action, etc.)
   * Manipulation patterns

### Example Report

```text
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

* Check microphone permissions
* Ensure PyAudio is installed:

```bash
pip install pyaudio
```

* Check internet connection (uses Google Speech API)

### AI not responding?

* Make sure Ollama is running:

```bash
ollama serve
```

* Pull the Llama3 model:

```bash
ollama pull llama3
```

### Dashboard not loading?

* Check if backend server started (look for `Dashboard will be available at: http://127.0.0.1:8080`)
* Open browser manually at http://127.0.0.1:8080
* Check firewall settings

### Link analysis not working?

* Ensure you're using the updated `backend/link_security.py`
* Check console output for analysis results
* Voice summary requires URL in the command

## Development

### Project Structure

* All voice commands are in `commands/` directory
* Backend API in `backend/server.py`
* Bridge logic in `backend/zyra_bridge.py`
* Security analysis in `backend/link_security.py`
* Dashboard UI in `desktop-dashboard/index.html`

### Adding New Commands

1. Add function in `commands/open_app.py` or `commands/close_app.py`
2. Import in `main.py`
3. Add elif clause in the main loop
4. Add to `COMMAND_MAP` in `backend/zyra_bridge.py`

## License

MIT License - Feel free to modify and use!

## Credits

* **ZYRA** - AI Assistant by Vasanthan Y
* **Ollama** - LLM runtime
* **Edge TTS** - Text-to-speech
* **Three.js** - 3D graphics
* **FastAPI** - Backend framework
