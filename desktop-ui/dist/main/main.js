/******/ (() => { // webpackBootstrap
/******/ 	"use strict";
/******/ 	var __webpack_modules__ = ({

/***/ "./src/main/backend-service.ts"
/*!*************************************!*\
  !*** ./src/main/backend-service.ts ***!
  \*************************************/
(__unused_webpack_module, exports, __webpack_require__) {


var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", ({ value: true }));
exports.BackendService = void 0;
const events_1 = __webpack_require__(/*! events */ "events");
const child_process_1 = __webpack_require__(/*! child_process */ "child_process");
const http = __importStar(__webpack_require__(/*! http */ "http"));
const zyra_paths_1 = __webpack_require__(/*! ./zyra-paths */ "./src/main/zyra-paths.ts");
const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 8080;
const STARTUP_TIMEOUT_MS = 45000;
const POLL_INTERVAL_MS = 500;
const LOG_LIMIT = 400;
// uvicorn / Windows socket errors emitted when the port is already taken.
const BIND_ERROR_RE = /address already in use|error while attempting to bind|only one usage of each socket address|WinError 10048|Errno 10048/i;
class BackendService extends events_1.EventEmitter {
    constructor(host = DEFAULT_HOST, port = DEFAULT_PORT) {
        super();
        this.proc = null;
        this.managedByElectron = false;
        /** First bind-failure line seen from the child, if any (port conflict). */
        this.bindError = null;
        this.logs = [];
        this.host = host;
        this.port = port;
        this.status = this.blankStatus();
    }
    blankStatus() {
        return {
            state: 'idle',
            url: null,
            host: this.host,
            port: this.port,
            pid: null,
            managedByElectron: false,
            adopted: false,
            error: null,
            startupMs: null,
            interpreter: null,
        };
    }
    getStatus() {
        return { ...this.status };
    }
    /** Most recent backend stdout/stderr lines, newest last. */
    getLogs() {
        return this.logs.slice();
    }
    // ── lifecycle ─────────────────────────────────────────────────────────────
    /**
     * Start (or adopt) the backend.
     *
     * Never throws: failures are reported through the returned status so the UI
     * can render them instead of dying with an unhandled rejection.
     */
    async start() {
        const startedAt = Date.now();
        this.update({ state: 'starting', error: null, startupMs: null });
        // 1. Reuse an already-running ZYRA backend rather than spawning a duplicate
        //    that would fail to bind the port.
        const existing = await this.probeHealth();
        if (existing.reachable && existing.zyra) {
            this.managedByElectron = false;
            this.update({
                state: 'ready',
                url: `http://${this.host}:${this.port}`,
                adopted: true,
                pid: null,
                managedByElectron: false,
                startupMs: Date.now() - startedAt,
            });
            return this.getStatus();
        }
        if (existing.reachable && !existing.zyra) {
            return this.fail(`Port ${this.port} is in use by a service that is not the ZYRA backend. ` +
                `Close the program using port ${this.port} (or free it) and retry.`);
        }
        return this.spawnBackend(startedAt);
    }
    async spawnBackend(startedAt) {
        this.bindError = null;
        // One resolution covers both modes: the bundled PyInstaller executable in an
        // installed build, or a Python interpreter running main.py in development.
        let launch;
        try {
            launch = (0, zyra_paths_1.resolveBackendLaunch)();
        }
        catch (err) {
            return this.fail(`Could not locate the ZYRA backend: ${String(err)}`);
        }
        this.recordLog(`desktop: launching backend -> ${launch.display}`);
        this.update({
            interpreter: launch.display,
            adopted: false,
            managedByElectron: true,
        });
        try {
            this.proc = (0, child_process_1.spawn)(launch.command, launch.args, {
                cwd: launch.cwd,
                env: {
                    ...process.env,
                    // The dashboard is hosted by Electron, so main.py must not open Edge.
                    ZYRA_NO_EDGE: '1',
                    PYTHONUNBUFFERED: '1',
                    PYTHONIOENCODING: 'utf-8',
                },
                stdio: ['ignore', 'pipe', 'pipe'],
                windowsHide: true,
            });
        }
        catch (err) {
            return this.fail(`Failed to launch the ZYRA backend (${launch.display}): ${String(err)}`);
        }
        const child = this.proc;
        child.stdout?.on('data', (data) => this.recordLog(data.toString()));
        child.stderr?.on('data', (data) => this.recordLog(data.toString()));
        child.on('error', (err) => {
            this.fail(`Python process error: ${err.message}`);
        });
        child.on('exit', (code) => {
            const wasActive = this.status.state === 'ready' || this.status.state === 'starting';
            this.proc = null;
            if (wasActive && this.managedByElectron) {
                this.update({
                    state: 'failed',
                    error: `The ZYRA backend exited unexpectedly (code ${code ?? 'null'}).`,
                    pid: null,
                });
            }
        });
        this.update({ pid: child.pid ?? null });
        // 2. Wait until /api/health genuinely answers.
        const ready = await this.pollUntilReady(STARTUP_TIMEOUT_MS);
        if (!ready) {
            this.killOwnedProcess();
            if (this.bindError) {
                return this.fail(`Port ${this.port} is already in use, so the ZYRA backend could not start. ` +
                    `Close the program using port ${this.port} and retry. ` +
                    `(${this.bindError})`);
            }
            const tail = this.logs.slice(-6).join(' | ');
            return this.fail(`The ZYRA backend did not become ready within ${STARTUP_TIMEOUT_MS / 1000}s.` +
                (tail ? ` Recent output: ${tail}` : ''));
        }
        this.update({
            state: 'ready',
            url: `http://${this.host}:${this.port}`,
            startupMs: Date.now() - startedAt,
        });
        return this.getStatus();
    }
    /**
     * Call the EXISTING FastAPI API on behalf of the renderer.
     *
     * Deliberately tiny: it only ever talks to the backend instance this class
     * resolved, it never changes a ZYRA API contract, and it lets the desktop UI
     * reach ZYRA's own HTTP endpoints without granting the renderer raw network
     * access.
     */
    async request(method, apiPath, payload) {
        const url = this.status.url;
        if (!url) {
            return { ok: false, status: 0, body: null, error: 'Backend is not ready' };
        }
        const target = new URL(apiPath, url);
        const body = payload === undefined ? null : Buffer.from(JSON.stringify(payload), 'utf-8');
        return new Promise((resolve) => {
            const req = http.request({
                hostname: target.hostname,
                port: target.port,
                path: target.pathname + target.search,
                method,
                headers: body
                    ? { 'Content-Type': 'application/json', 'Content-Length': body.length }
                    : undefined,
                timeout: 30000,
            }, (res) => {
                const chunks = [];
                res.on('data', (chunk) => chunks.push(chunk));
                res.on('end', () => {
                    const text = Buffer.concat(chunks).toString('utf-8');
                    let parsed = text;
                    try {
                        parsed = JSON.parse(text);
                    }
                    catch {
                        /* leave as text */
                    }
                    const status = res.statusCode ?? 0;
                    resolve({ ok: status >= 200 && status < 300, status, body: parsed, error: null });
                });
            });
            req.on('timeout', () => req.destroy(new Error('Request timed out')));
            req.on('error', (err) => resolve({ ok: false, status: 0, body: null, error: err.message }));
            if (body)
                req.write(body);
            req.end();
        });
    }
    /** Re-attempt startup after a failure (surfaced by the UI Retry button). */
    async retry() {
        this.killOwnedProcess();
        return this.start();
    }
    /**
     * Public shutdown entry point, called when the app is closing.
     * Only ever terminates a process this instance started; an adopted backend is
     * left running because Electron does not own it.
     */
    async stop() {
        this.killOwnedProcess();
        this.update({ state: 'stopped', pid: null });
    }
    /** Synchronous best-effort reap for process.on('exit'). */
    forceKillSync() {
        if (this.proc && this.managedByElectron && typeof this.proc.pid === 'number') {
            this.killTreeSync(this.proc.pid);
            this.proc = null;
        }
    }
    isRunning() {
        return this.status.state === 'ready';
    }
    // ── internals ────────────────────────────────────────────────────────────
    update(patch) {
        this.status = { ...this.status, ...patch };
        this.emit('status', this.getStatus());
    }
    fail(message) {
        this.recordLog(`desktop: ${message}`);
        this.update({ state: 'failed', error: message, startupMs: null });
        return this.getStatus();
    }
    recordLog(chunk) {
        const lines = chunk.split(/\r?\n/);
        for (const line of lines) {
            const trimmed = line.trimEnd();
            if (!trimmed)
                continue;
            this.logs.push(trimmed);
            // A bind failure is a definitive "port is taken" signal; remember the
            // first one so startup can fail fast with an actionable message.
            if (this.bindError === null && BIND_ERROR_RE.test(trimmed)) {
                this.bindError = trimmed;
            }
            // Mirror to the terminal so nothing is hidden during development.
            console.log(`[zyra-backend] ${trimmed}`);
        }
        if (this.logs.length > LOG_LIMIT) {
            this.logs = this.logs.slice(-LOG_LIMIT);
        }
    }
    probeHealth() {
        return new Promise((resolve) => {
            const req = http.request({
                hostname: this.host,
                port: this.port,
                path: '/api/health',
                method: 'GET',
                timeout: 2500,
            }, (res) => {
                const chunks = [];
                res.on('data', (chunk) => chunks.push(chunk));
                res.on('end', () => {
                    let zyra = false;
                    try {
                        const parsed = JSON.parse(Buffer.concat(chunks).toString('utf-8'));
                        // Require ZYRA's own sentinel field. A generic {"status":"ok"}
                        // from an unrelated service on the same port must NOT be mistaken
                        // for our backend, or Electron would adopt it and the dashboard
                        // would fail to load.
                        zyra = parsed.zyra === 'running';
                    }
                    catch {
                        /* not JSON -> not a ZYRA health payload */
                    }
                    resolve({ reachable: true, zyra });
                });
            });
            req.on('timeout', () => {
                req.destroy();
                resolve({ reachable: false, zyra: false });
            });
            req.on('error', () => resolve({ reachable: false, zyra: false }));
            req.end();
        });
    }
    /** Poll /api/health until the backend genuinely answers, or we give up. */
    async pollUntilReady(timeoutMs) {
        const deadline = Date.now() + timeoutMs;
        while (Date.now() < deadline) {
            // Definitive bind failure: no point waiting for the full timeout.
            if (this.bindError)
                return false;
            if (!this.proc && this.status.state === 'failed')
                return false;
            const health = await this.probeHealth();
            if (health.reachable && health.zyra)
                return true;
            await this.delay(POLL_INTERVAL_MS);
        }
        return false;
    }
    delay(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }
    /**
     * Terminate the backend process tree that this instance owns.
     * Does nothing for an adopted backend we do not own.
     *
     * IMPORTANT (Windows): the virtualenv launcher re-executes the real
     * interpreter as a CHILD process, so the PID Node spawns is only the parent of
     * the process actually serving HTTP. Killing just that PID would leave uvicorn
     * orphaned on port 8080, so on Windows the whole tree is terminated.
     */
    killOwnedProcess() {
        if (!this.proc)
            return;
        if (!this.managedByElectron) {
            this.proc = null;
            return;
        }
        const pid = this.proc.pid;
        this.proc = null;
        this.managedByElectron = false;
        if (typeof pid === 'number') {
            this.killTreeSync(pid);
        }
    }
    killTreeSync(pid) {
        try {
            if (process.platform === 'win32') {
                (0, child_process_1.spawnSync)('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true });
            }
            else {
                process.kill(pid, 'SIGTERM');
            }
        }
        catch (err) {
            console.error('Failed to terminate backend process tree:', err);
        }
    }
}
exports.BackendService = BackendService;


/***/ },

/***/ "./src/main/main.ts"
/*!**************************!*\
  !*** ./src/main/main.ts ***!
  \**************************/
(__unused_webpack_module, exports, __webpack_require__) {


var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", ({ value: true }));
const electron_1 = __webpack_require__(/*! electron */ "electron");
const path = __importStar(__webpack_require__(/*! path */ "path"));
const python_bridge_1 = __webpack_require__(/*! ./python-bridge */ "./src/main/python-bridge.ts");
const backend_service_1 = __webpack_require__(/*! ./backend-service */ "./src/main/backend-service.ts");
let mainWindow = null;
let desktopWindow = null;
let pythonBridge = null;
let backendService = null;
let dashboardLoaded = false;
let quitting = false;
let shutdownDone = false;
function preloadPath() {
    return path.join(__dirname, 'preload.js');
}
/** Path to a file emitted next to main.js by webpack (dist/renderer/<name>). */
function rendererFile(name) {
    return path.join(__dirname, '..', 'renderer', name);
}
function sendBackendStatus(status) {
    for (const win of electron_1.BrowserWindow.getAllWindows()) {
        if (!win.isDestroyed()) {
            win.webContents.send('backend:status', status);
        }
    }
}
/** True once the FastAPI backend is serving (spawned by us or adopted). */
function backendReady() {
    return !!backendService && backendService.getStatus().state === 'ready';
}
/** Call a FastAPI endpoint and return the parsed body; throws on failure. */
async function backendCall(method, apiPath, payload) {
    if (!backendService)
        throw new Error('Backend not initialised');
    const result = await backendService.request(method, apiPath, payload);
    if (!result.ok) {
        const body = result.body;
        throw new Error(body?.error || result.error || `Backend request failed (${result.status})`);
    }
    return result.body;
}
/**
 * The FastAPI backend is the primary data path for the React UI. The legacy
 * `bridge_server.py` process is started here ONLY as a fallback, so a normal
 * desktop session runs a single Python process instead of two.
 */
function ensureBridge() {
    try {
        if (!pythonBridge) {
            pythonBridge = new python_bridge_1.PythonBridge();
            console.log('desktop: legacy Python bridge started as a fallback path');
        }
        if (!pythonBridge.isRunning()) {
            pythonBridge.start();
        }
        return pythonBridge;
    }
    catch (err) {
        console.error('desktop: failed to start the Python bridge fallback:', err);
        return null;
    }
}
/** Fallback path: talk to the lazily-started legacy Python bridge. */
async function bridgeCommand(type, data) {
    const bridge = ensureBridge();
    if (!bridge)
        throw new Error('Python bridge unavailable');
    return bridge.sendCommand({ type, data });
}
function createWindow() {
    mainWindow = new electron_1.BrowserWindow({
        width: 1280,
        height: 860,
        minWidth: 1000,
        minHeight: 700,
        backgroundColor: '#0c0c14',
        title: 'ZYRA - AI Assistant',
        webPreferences: {
            preload: preloadPath(),
            contextIsolation: true,
            nodeIntegration: false,
        },
    });
    // Show the startup screen first; the holographic dashboard is swapped in once
    // the FastAPI backend reports ready. The once() guard prevents a reload loop.
    void mainWindow.loadFile(rendererFile('splash.html'));
    mainWindow.webContents.once('did-finish-load', () => {
        if (backendService && backendService.isRunning() && !dashboardLoaded) {
            loadDashboard();
        }
    });
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}
/** Load the existing Three.js dashboard, served by the local FastAPI backend. */
function loadDashboard() {
    if (!mainWindow || !backendService)
        return;
    const status = backendService.getStatus();
    if (status.state !== 'ready' || !status.url)
        return;
    dashboardLoaded = true;
    mainWindow.loadURL(status.url).catch((err) => {
        console.error('Failed to load the ZYRA dashboard:', err);
    });
}
/** The existing React desktop UI, kept available as a secondary window. */
function openDesktopUiWindow() {
    if (desktopWindow && !desktopWindow.isDestroyed()) {
        desktopWindow.focus();
        return;
    }
    desktopWindow = new electron_1.BrowserWindow({
        // The React window's index.html renders a fixed 1420x900 laptop bezel, so
        // the window must be at least that large or the UI gets clipped.
        width: 1480,
        height: 960,
        minWidth: 1100,
        minHeight: 760,
        title: 'ZYRA - Desktop UI',
        backgroundColor: '#0a0a0f',
        webPreferences: {
            preload: preloadPath(),
            contextIsolation: true,
            nodeIntegration: false,
        },
    });
    desktopWindow.loadFile(rendererFile('index.html')).catch((err) => {
        console.error('Failed to load the ZYRA desktop UI window:', err);
    });
    desktopWindow.on('closed', () => {
        desktopWindow = null;
    });
}
function buildMenu() {
    const template = [
        {
            label: 'File',
            submenu: [
                { label: 'Reload Dashboard', accelerator: 'CmdOrCtrl+R', click: () => { dashboardLoaded = false; loadDashboard(); } },
                { label: 'Open Desktop UI', accelerator: 'CmdOrCtrl+Shift+D', click: () => openDesktopUiWindow() },
                {
                    label: 'Open Backend API Docs',
                    click: () => {
                        const url = backendService?.getStatus().url;
                        if (url)
                            void electron_1.shell.openExternal(`${url}/docs`);
                    },
                },
                { type: 'separator' },
                { role: 'quit' },
            ],
        },
        {
            label: 'View',
            submenu: [
                { role: 'toggleDevTools' },
                { role: 'resetZoom' },
                { role: 'zoomIn' },
                { role: 'zoomOut' },
                { type: 'separator' },
                { role: 'togglefullscreen' },
            ],
        },
        {
            label: 'Help',
            submenu: [
                { label: 'Backend Status', click: () => sendBackendStatus(backendService?.getStatus() ?? null) },
            ],
        },
    ];
    electron_1.Menu.setApplicationMenu(electron_1.Menu.buildFromTemplate(template));
}
async function shutdown() {
    if (shutdownDone)
        return;
    shutdownDone = true;
    try {
        if (pythonBridge)
            pythonBridge.stop();
    }
    catch (err) {
        console.error('Error stopping the Python bridge:', err);
    }
    try {
        if (backendService)
            await backendService.stop();
    }
    catch (err) {
        console.error('Error stopping the ZYRA backend:', err);
    }
}
electron_1.app.whenReady().then(async () => {
    buildMenu();
    createWindow();
    // Launch flag: `electron . --desktop-ui` opens the classic React desktop UI
    // window at startup (useful for developing/verifying the secondary window).
    if (process.argv.includes('--desktop-ui')) {
        openDesktopUiWindow();
    }
    // NOTE: the legacy `bridge_server.py` bridge is NOT started here. The React UI
    // talks to the FastAPI backend below, so a normal desktop session runs a
    // single Python process. The bridge is started lazily by ensureBridge() only
    // if a request ever needs the fallback path.
    //
    // Primary: start ZYRA's FastAPI backend, then load the dashboard when ready.
    backendService = new backend_service_1.BackendService();
    backendService.on('status', (status) => {
        sendBackendStatus(status);
        if (status.state === 'ready' && !dashboardLoaded) {
            loadDashboard();
        }
        if (status.state === 'failed') {
            console.error('ZYRA backend failed to start:', status.error);
        }
    });
    const result = await backendService.start();
    if (result.state === 'ready' && !dashboardLoaded) {
        loadDashboard();
    }
    electron_1.app.on('activate', () => {
        if (electron_1.BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});
electron_1.app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        electron_1.app.quit();
    }
});
electron_1.app.on('before-quit', () => {
    quitting = true;
});
electron_1.app.on('will-quit', () => {
    void shutdown();
});
// Last-resort synchronous reap so a killed Electron never orphans uvicorn.
process.on('exit', () => {
    if (quitting && backendService) {
        backendService.forceKillSync();
    }
});
// IPC Handlers
//
// Primary path: the running FastAPI backend (one Python process, the same one
// serving the dashboard). Fallback: the legacy `bridge_server.py` bridge, which
// is started lazily and only if the backend cannot serve the request. This
// keeps every existing React feature working while avoiding a second Python
// process in normal use.
// Send message to Zyra's AI brain (Ollama).
electron_1.ipcMain.handle('ai:chat', async (_event, message) => {
    if (backendReady()) {
        const body = (await backendCall('POST', '/api/chat', { message }));
        if (typeof body?.response === 'string')
            return body.response;
        throw new Error('Unexpected response from /api/chat');
    }
    return (await bridgeCommand('chat', message));
});
// Execute a system command.
electron_1.ipcMain.handle('command:execute', async (_event, command) => {
    if (backendReady()) {
        return backendCall('POST', '/api/command', { command });
    }
    return bridgeCommand('command', command);
});
// Toggle voice listening. ZYRA's real voice loop lives in the backend process;
// this keeps the React UI's control surface working as before.
//
// Lifecycle contract (shared with VoiceControl + bridge_server.py):
//   Idle -> Listening -> Recognizing -> Processing -> Response displayed -> Idle
// `enabled=false` NEVER starts a capture: it returns {listening:false}
// immediately (idempotent, safe to call twice). The legacy bridge capture is
// synchronous and blocking, so an in-flight capture cannot be cancelled
// mid-listen by flipping the toggle — the stop call is serialized behind it
// and the UI must treat the promise as the single source of truth.
//
// NOTE: /api/voice accepts transcribed TEXT only (it cannot capture audio),
// so microphone capture always goes through the legacy bridge. The
// FastAPI backend is still the command-routing authority: the bridge
// forwards every transcript to backend/server.py process_voice_command(),
// the same function /api/voice and /ws 'voice' use.
let voiceInFlight = null;
electron_1.ipcMain.handle('voice:toggle', async (_event, enabled) => {
    if (!enabled) {
        // Stand down: never open the microphone on a stop request.
        // If a capture is in flight it runs to its timeout on the bridge side;
        // serialize behind it instead of opening a second session.
        if (voiceInFlight) {
            try {
                await voiceInFlight;
            }
            catch {
                /* the racing capture already reported its own error */
            }
        }
        try {
            await bridgeCommand('voice_stop', null);
        }
        catch {
            /* best-effort: absence of a stop ack must not fail the UI */
        }
        return { transcript: '', response: '', listening: false };
    }
    if (voiceInFlight) {
        throw new Error('Voice capture already in progress. Wait for it to finish.');
    }
    const pending = bridgeCommand('voice_toggle', true);
    voiceInFlight = pending;
    try {
        return await pending;
    }
    finally {
        voiceInFlight = null;
    }
});
// Get voice status.
electron_1.ipcMain.handle('voice:status', async () => {
    return bridgeCommand('voice_status', null);
});
// Remember something.
electron_1.ipcMain.handle('memory:remember', async (_event, key, value) => {
    if (backendReady()) {
        return backendCall('POST', '/api/memory/remember', { key, value });
    }
    return bridgeCommand('remember', { key, value });
});
// Recall something.
electron_1.ipcMain.handle('memory:recall', async (_event, key) => {
    if (backendReady()) {
        const body = (await backendCall('POST', '/api/memory/recall', { key }));
        return body?.data ?? null;
    }
    return bridgeCommand('recall', key);
});
// System Monitor metrics.
electron_1.ipcMain.handle('system:metrics', async () => {
    if (backendReady()) {
        return backendCall('GET', '/api/system/metrics');
    }
    return bridgeCommand('system_metrics', null);
});
// Get available commands list
electron_1.ipcMain.handle('commands:list', async () => {
    return [
        { id: 'open_chrome', label: 'Open Chrome', category: 'apps' },
        { id: 'open_vscode', label: 'Open VS Code', category: 'apps' },
        { id: 'open_notepad', label: 'Open Notepad', category: 'apps' },
        { id: 'open_calculator', label: 'Open Calculator', category: 'apps' },
        { id: 'open_cmd', label: 'Open CMD', category: 'apps' },
        { id: 'open_powershell', label: 'Open PowerShell', category: 'apps' },
        { id: 'open_task_manager', label: 'Task Manager', category: 'apps' },
        { id: 'open_settings', label: 'Open Settings', category: 'apps' },
        { id: 'open_file_explorer', label: 'File Explorer', category: 'apps' },
        { id: 'open_google', label: 'Open Google', category: 'web' },
        { id: 'open_youtube', label: 'Open YouTube', category: 'web' },
        { id: 'open_github', label: 'Open GitHub', category: 'web' },
        { id: 'open_chatgpt', label: 'Open ChatGPT', category: 'web' },
        { id: 'open_gmail', label: 'Open Gmail', category: 'web' },
        { id: 'open_leetcode', label: 'Open LeetCode', category: 'web' },
        { id: 'open_linkedin', label: 'Open LinkedIn', category: 'web' },
        { id: 'monitor_system', label: 'Monitor System', category: 'system' },
        { id: 'volume_up', label: 'Volume Up', category: 'system' },
        { id: 'volume_down', label: 'Volume Down', category: 'system' },
        { id: 'mute', label: 'Mute', category: 'system' },
        { id: 'screenshot', label: 'Screenshot', category: 'system' },
        { id: 'lock_pc', label: 'Lock PC', category: 'system' },
        { id: 'shutdown', label: 'Shutdown', category: 'system' },
        { id: 'restart', label: 'Restart', category: 'system' },
        { id: 'sleep', label: 'Sleep', category: 'system' },
        { id: 'wifi_on', label: 'Wi-Fi On', category: 'system' },
        { id: 'wifi_off', label: 'Wi-Fi Off', category: 'system' },
        { id: 'empty_recycle_bin', label: 'Empty Recycle Bin', category: 'system' },
        { id: 'current_time', label: 'Current Time', category: 'info' },
        { id: 'current_date', label: 'Current Date', category: 'info' },
        { id: 'play_music', label: 'Play Music', category: 'media' },
        { id: 'open_camera', label: 'Open Camera', category: 'media' },
    ];
});
// ── Backend (FastAPI) IPC ───────────────────────────────────────────────────
// Current FastAPI backend lifecycle status (splash screen / React UI).
electron_1.ipcMain.handle('backend:status', () => backendService?.getStatus() ?? null);
// Recent backend stdout/stderr, for the failure panel.
electron_1.ipcMain.handle('backend:logs', () => backendService?.getLogs() ?? []);
// Retry backend startup (surfaced by the UI Retry button).
electron_1.ipcMain.handle('backend:restart', async () => {
    if (!backendService)
        return null;
    dashboardLoaded = false;
    return backendService.retry();
});
// Call the existing FastAPI API on the renderer's behalf.
electron_1.ipcMain.handle('backend:request', async (_event, method, apiPath, payload) => {
    if (!backendService) {
        return { ok: false, status: 0, body: null, error: 'Backend not initialised' };
    }
    return backendService.request(method, apiPath, payload);
});
// Open the existing React desktop UI in its own window.
electron_1.ipcMain.handle('ui:open-desktop', () => {
    openDesktopUiWindow();
    return true;
});


/***/ },

/***/ "./src/main/python-bridge.ts"
/*!***********************************!*\
  !*** ./src/main/python-bridge.ts ***!
  \***********************************/
(__unused_webpack_module, exports, __webpack_require__) {


var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", ({ value: true }));
exports.PythonBridge = void 0;
const child_process_1 = __webpack_require__(/*! child_process */ "child_process");
const fs = __importStar(__webpack_require__(/*! fs */ "fs"));
const path = __importStar(__webpack_require__(/*! path */ "path"));
/**
 * Resolve the Python interpreter the same way the FastAPI backend launcher
 * does (desktop-ui/src/main/zyra-paths.ts resolvePython): explicit
 * ZYRA_PYTHON override first, then <root>/.venv, then <root>/venv, then
 * PATH. Never blindly uses a system `python` when the project environment
 * exists.
 */
function resolveBridgePython(root) {
    const override = process.env.ZYRA_PYTHON;
    if (override && override.trim().length > 0)
        return override.trim();
    const isWindows = process.platform === 'win32';
    const candidates = isWindows
        ? [path.join(root, '.venv', 'Scripts', 'python.exe'), path.join(root, 'venv', 'Scripts', 'python.exe')]
        : [path.join(root, '.venv', 'bin', 'python'), path.join(root, 'venv', 'bin', 'python')];
    for (const file of candidates) {
        try {
            if (fs.existsSync(file))
                return file;
        }
        catch {
            /* ignore and continue */
        }
    }
    return isWindows ? 'python' : 'python3';
}
class PythonBridge {
    constructor() {
        this.process = null;
        this.requestId = 0;
        this.pendingRequests = new Map();
        this.buffer = '';
    }
    start() {
        // __dirname is dist/main/ ; bridge_server.py is at desktop-ui/bridge_server.py
        // Project root is two levels up (dist/main -> desktop-ui -> root).
        const root = path.join(__dirname, '..', '..');
        const scriptPath = path.join(root, 'bridge_server.py');
        const python = resolveBridgePython(root);
        this.process = (0, child_process_1.spawn)(python, [scriptPath], {
            stdio: ['pipe', 'pipe', 'pipe'],
            cwd: root,
        });
        this.process.stdout?.on('data', (data) => {
            this.buffer += data.toString();
            this.processBuffer();
        });
        this.process.stderr?.on('data', (data) => {
            console.error('Python Bridge Error:', data.toString());
        });
        this.process.on('exit', (code) => {
            console.log('Python process exited with code:', code);
            this.process = null;
            // Reject all pending requests
            for (const [, pending] of this.pendingRequests) {
                pending.reject(new Error('Python process exited'));
            }
            this.pendingRequests.clear();
        });
        this.process.on('error', (err) => {
            console.error('Failed to start Python process:', err);
        });
    }
    stop() {
        if (this.process) {
            this.process.kill();
            this.process = null;
        }
    }
    async sendCommand(command) {
        return new Promise((resolve, reject) => {
            if (!this.process || !this.process.stdin) {
                reject(new Error('Python process not running'));
                return;
            }
            const id = ++this.requestId;
            this.pendingRequests.set(id, { resolve, reject });
            const message = JSON.stringify({ id, ...command }) + '\n';
            this.process.stdin.write(message);
        });
    }
    processBuffer() {
        const lines = this.buffer.split('\n');
        // Keep the last incomplete line in the buffer
        this.buffer = lines.pop() || '';
        for (const line of lines) {
            if (!line.trim())
                continue;
            try {
                const response = JSON.parse(line);
                const pending = this.pendingRequests.get(response.id);
                if (pending) {
                    this.pendingRequests.delete(response.id);
                    if (response.success) {
                        pending.resolve(response.data);
                    }
                    else {
                        pending.reject(new Error(response.error || 'Unknown error'));
                    }
                }
            }
            catch (e) {
                console.error('Failed to parse Python response:', line);
            }
        }
    }
    isRunning() {
        return this.process !== null && !this.process.killed;
    }
}
exports.PythonBridge = PythonBridge;


/***/ },

/***/ "./src/main/zyra-paths.ts"
/*!********************************!*\
  !*** ./src/main/zyra-paths.ts ***!
  \********************************/
(__unused_webpack_module, exports, __webpack_require__) {


var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", ({ value: true }));
exports.isProjectRoot = isProjectRoot;
exports.resolveProjectRoot = resolveProjectRoot;
exports.resolvePython = resolvePython;
exports.isPackagedBackendDir = isPackagedBackendDir;
exports.resolveBackendLaunch = resolveBackendLaunch;
const fs = __importStar(__webpack_require__(/*! fs */ "fs"));
const path = __importStar(__webpack_require__(/*! path */ "path"));
/** Electron injects `resourcesPath` at runtime; typed defensively. */
function resourcesPath() {
    const value = process.resourcesPath;
    return typeof value === 'string' && value.length > 0 ? value : null;
}
/** A directory counts as the ZYRA project root when both markers exist. */
function isProjectRoot(dir) {
    try {
        return (fs.existsSync(path.join(dir, 'main.py')) &&
            fs.existsSync(path.join(dir, 'desktop-dashboard', 'index.html')) &&
            fs.existsSync(path.join(dir, 'backend', 'server.py')));
    }
    catch {
        return false;
    }
}
/**
 * Locate the ZYRA project root.
 *
 * Order:
 *   1. Packaged builds: `<resourcesPath>/zyra` (where a future PyInstaller
 *      bundle will be placed via `extraResources`), then `resourcesPath`.
 *   2. Development: walk up from this module's directory looking for the markers.
 *   3. Documented fallback of two levels up from `__dirname`, which is correct
 *      for the current dev layout (`desktop-ui/dist/main` -> `desktop-ui` -> root).
 */
function resolveProjectRoot(startDir) {
    const base = startDir || __dirname;
    const packaged = resourcesPath();
    if (packaged) {
        const bundled = path.join(packaged, 'zyra');
        if (isProjectRoot(bundled))
            return bundled;
        if (isProjectRoot(packaged))
            return packaged;
    }
    let dir = base;
    for (let i = 0; i < 8; i += 1) {
        if (isProjectRoot(dir))
            return dir;
        const parent = path.dirname(dir);
        if (parent === dir)
            break;
        dir = parent;
    }
    return path.resolve(base, '..', '..');
}
/**
 * Pick the Python interpreter used to run ZYRA's backend and bridge.
 *
 * Precedence (requirement: avoid depending on a global `python`):
 *   1. `ZYRA_PYTHON` — explicit override. Honoured verbatim (even if it does not
 *      exist) so the caller surfaces a precise "not found" error rather than
 *      silently running a different interpreter than the user asked for.
 *   2. `<root>/.venv` — the project's own virtual environment.
 *   3. `<root>/venv`  — a conventionally named alternative.
 *   4. `python` / `python3` from PATH — last resort, logged as such.
 */
function resolvePython(root) {
    const override = process.env.ZYRA_PYTHON;
    if (override && override.trim().length > 0) {
        const command = override.trim();
        return { command, source: 'ZYRA_PYTHON', display: command };
    }
    const isWindows = process.platform === 'win32';
    const candidates = isWindows
        ? [
            { file: path.join(root, '.venv', 'Scripts', 'python.exe'), source: 'venv' },
            { file: path.join(root, 'venv', 'Scripts', 'python.exe'), source: 'venv-fallback' },
        ]
        : [
            { file: path.join(root, '.venv', 'bin', 'python'), source: 'venv' },
            { file: path.join(root, 'venv', 'bin', 'python'), source: 'venv-fallback' },
        ];
    for (const candidate of candidates) {
        try {
            if (fs.existsSync(candidate.file)) {
                return { command: candidate.file, source: candidate.source, display: candidate.file };
            }
        }
        catch {
            /* ignore and continue */
        }
    }
    const fallback = isWindows ? 'python' : 'python3';
    return { command: fallback, source: 'PATH', display: `${fallback} (from PATH)` };
}
/** File name of the PyInstaller-built backend shipped inside `resources/zyra`. */
function packagedBackendCandidates(dir) {
    return process.platform === 'win32'
        ? [path.join(dir, 'ZYRA-backend.exe'), path.join(dir, 'ZYRA-backend')]
        : [path.join(dir, 'ZYRA-backend'), path.join(dir, 'ZYRA-backend.exe')];
}
/** True when this directory holds the bundled backend executable. */
function isPackagedBackendDir(dir) {
    return packagedBackendCandidates(dir).some((file) => {
        try {
            return fs.existsSync(file);
        }
        catch {
            return false;
        }
    });
}
/**
 * Work out how to start the ZYRA backend.
 *
 * Precedence:
 *   1. `ZYRA_BACKEND`  — explicit path to a backend executable (honoured verbatim
 *                        so a bad override surfaces a precise error).
 *   2. Packaged build  — `<resourcesPath>/zyra/ZYRA-backend(.exe)`, i.e. the
 *                        PyInstaller bundle shipped by electron-builder. No
 *                        Python, npm or source checkout required.
 *   3. Development     — a Python interpreter (see resolvePython) running the
 *                        project's `main.py`.
 *
 * `process.resourcesPath` always exists in Electron, but only an installed
 * build actually contains the bundled backend, so the existence check below is
 * what really distinguishes the two modes.
 */
function resolveBackendLaunch(startDir) {
    const override = process.env.ZYRA_BACKEND;
    if (override && override.trim().length > 0) {
        const command = override.trim();
        return {
            command,
            args: [],
            cwd: path.dirname(command),
            display: `${command} (from ZYRA_BACKEND)`,
            source: 'ZYRA_BACKEND',
        };
    }
    const resources = resourcesPath();
    if (resources) {
        for (const dir of [path.join(resources, 'zyra'), resources]) {
            if (isPackagedBackendDir(dir)) {
                const exe = packagedBackendCandidates(dir).find((f) => fs.existsSync(f));
                return {
                    command: exe,
                    args: [],
                    cwd: dir,
                    display: `${exe} (packaged backend)`,
                    source: 'packaged',
                };
            }
        }
    }
    const root = resolveProjectRoot(startDir);
    const python = resolvePython(root);
    const entry = path.join(root, 'main.py');
    return {
        command: python.command,
        args: [entry],
        cwd: root,
        display: `${python.display} ${entry}`,
        source: python.source,
    };
}


/***/ },

/***/ "child_process"
/*!********************************!*\
  !*** external "child_process" ***!
  \********************************/
(module) {

module.exports = require("child_process");

/***/ },

/***/ "electron"
/*!***************************!*\
  !*** external "electron" ***!
  \***************************/
(module) {

module.exports = require("electron");

/***/ },

/***/ "events"
/*!*************************!*\
  !*** external "events" ***!
  \*************************/
(module) {

module.exports = require("events");

/***/ },

/***/ "fs"
/*!*********************!*\
  !*** external "fs" ***!
  \*********************/
(module) {

module.exports = require("fs");

/***/ },

/***/ "http"
/*!***********************!*\
  !*** external "http" ***!
  \***********************/
(module) {

module.exports = require("http");

/***/ },

/***/ "path"
/*!***********************!*\
  !*** external "path" ***!
  \***********************/
(module) {

module.exports = require("path");

/***/ }

/******/ 	});
/************************************************************************/
/******/ 	// The module cache
/******/ 	const __webpack_module_cache__ = {};
/******/ 	
/******/ 	// The require function
/******/ 	function __webpack_require__(moduleId) {
/******/ 		// Check if module is in cache
/******/ 		const cachedModule = __webpack_module_cache__[moduleId];
/******/ 		if (cachedModule !== undefined) {
/******/ 			return cachedModule.exports;
/******/ 		}
/******/ 		// Create a new module (and put it into the cache)
/******/ 		const module = __webpack_module_cache__[moduleId] = {
/******/ 			// no module.id needed
/******/ 			// no module.loaded needed
/******/ 			exports: {}
/******/ 		};
/******/ 	
/******/ 		// Execute the module function
/******/ 		if (!(moduleId in __webpack_modules__)) {
/******/ 			delete __webpack_module_cache__[moduleId];
/******/ 			const e = new Error("Cannot find module '" + moduleId + "'");
/******/ 			e.code = 'MODULE_NOT_FOUND';
/******/ 			throw e;
/******/ 		}
/******/ 		__webpack_modules__[moduleId].call(module.exports, module, module.exports, __webpack_require__);
/******/ 	
/******/ 		// Return the exports of the module
/******/ 		return module.exports;
/******/ 	}
/******/ 	
/************************************************************************/
/******/ 	
/******/ 	// startup
/******/ 	// Load entry module and return exports
/******/ 	// This entry module is referenced by other modules so it can't be inlined
/******/ 	let __webpack_exports__ = __webpack_require__("./src/main/main.ts");
/******/ 	
/******/ })()
;
//# sourceMappingURL=main.js.map