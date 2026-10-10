import { app, BrowserWindow, ipcMain, Menu, shell, MenuItemConstructorOptions } from 'electron';
import * as path from 'path';
import { PythonBridge } from './python-bridge';
import { BackendService, BackendStatus } from './backend-service';

let mainWindow: BrowserWindow | null = null;
let desktopWindow: BrowserWindow | null = null;
let pythonBridge: PythonBridge | null = null;
let backendService: BackendService | null = null;
let dashboardLoaded = false;
let quitting = false;
let shutdownDone = false;

function preloadPath(): string {
  return path.join(__dirname, 'preload.js');
}

/** Path to a file emitted next to main.js by webpack (dist/renderer/<name>). */
function rendererFile(name: string): string {
  return path.join(__dirname, '..', 'renderer', name);
}

function sendBackendStatus(status: BackendStatus | null): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send('backend:status', status);
    }
  }
}

/** True once the FastAPI backend is serving (spawned by us or adopted). */
function backendReady(): boolean {
  return !!backendService && backendService.getStatus().state === 'ready';
}

/** Call a FastAPI endpoint and return the parsed body; throws on failure. */
async function backendCall(method: string, apiPath: string, payload?: unknown): Promise<unknown> {
  if (!backendService) throw new Error('Backend not initialised');
  const result = await backendService.request(method, apiPath, payload);
  if (!result.ok) {
    const body = result.body as { error?: string } | null;
    throw new Error(body?.error || result.error || `Backend request failed (${result.status})`);
  }
  return result.body;
}

/**
 * The FastAPI backend is the primary data path for the React UI. The legacy
 * `bridge_server.py` process is started here ONLY as a fallback, so a normal
 * desktop session runs a single Python process instead of two.
 */
function ensureBridge(): PythonBridge | null {
  try {
    if (!pythonBridge) {
      pythonBridge = new PythonBridge();
      console.log('desktop: legacy Python bridge started as a fallback path');
    }
    if (!pythonBridge.isRunning()) {
      pythonBridge.start();
    }
    return pythonBridge;
  } catch (err) {
    console.error('desktop: failed to start the Python bridge fallback:', err);
    return null;
  }
}

/** Fallback path: talk to the lazily-started legacy Python bridge. */
async function bridgeCommand(type: string, data: unknown): Promise<unknown> {
  const bridge = ensureBridge();
  if (!bridge) throw new Error('Python bridge unavailable');
  return bridge.sendCommand({ type, data });
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
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
function loadDashboard(): void {
  if (!mainWindow || !backendService) return;
  const status = backendService.getStatus();
  if (status.state !== 'ready' || !status.url) return;
  dashboardLoaded = true;
  mainWindow.loadURL(status.url).catch((err: Error) => {
    console.error('Failed to load the ZYRA dashboard:', err);
  });
}

/** The existing React desktop UI, kept available as a secondary window. */
function openDesktopUiWindow(): void {
  if (desktopWindow && !desktopWindow.isDestroyed()) {
    desktopWindow.focus();
    return;
  }
  desktopWindow = new BrowserWindow({
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
  desktopWindow.loadFile(rendererFile('index.html')).catch((err: Error) => {
    console.error('Failed to load the ZYRA desktop UI window:', err);
  });
  desktopWindow.on('closed', () => {
    desktopWindow = null;
  });
}

function buildMenu(): void {
  const template: MenuItemConstructorOptions[] = [
    {
      label: 'File',
      submenu: [
        { label: 'Reload Dashboard', accelerator: 'CmdOrCtrl+R', click: () => { dashboardLoaded = false; loadDashboard(); } },
        { label: 'Open Desktop UI', accelerator: 'CmdOrCtrl+Shift+D', click: () => openDesktopUiWindow() },
        {
          label: 'Open Backend API Docs',
          click: () => {
            const url = backendService?.getStatus().url;
            if (url) void shell.openExternal(`${url}/docs`);
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
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function shutdown(): Promise<void> {
  if (shutdownDone) return;
  shutdownDone = true;
  try {
    if (pythonBridge) pythonBridge.stop();
  } catch (err) {
    console.error('Error stopping the Python bridge:', err);
  }
  try {
    if (backendService) await backendService.stop();
  } catch (err) {
    console.error('Error stopping the ZYRA backend:', err);
  }
}

app.whenReady().then(async () => {
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
  backendService = new BackendService();
  backendService.on('status', (status: BackendStatus) => {
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

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  quitting = true;
});

app.on('will-quit', () => {
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
ipcMain.handle('ai:chat', async (_event, message: string): Promise<string> => {
  if (backendReady()) {
    const body = (await backendCall('POST', '/api/chat', { message })) as {
      success?: boolean;
      response?: string;
    };
    if (typeof body?.response === 'string') return body.response;
    throw new Error('Unexpected response from /api/chat');
  }
  return (await bridgeCommand('chat', message)) as string;
});

// Execute a system command.
ipcMain.handle('command:execute', async (_event, command: string): Promise<unknown> => {
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
let voiceInFlight: Promise<unknown> | null = null;

ipcMain.handle('voice:toggle', async (_event, enabled: boolean): Promise<unknown> => {
  if (!enabled) {
    // Stand down: never open the microphone on a stop request.
    // If a capture is in flight it runs to its timeout on the bridge side;
    // serialize behind it instead of opening a second session.
    if (voiceInFlight) {
      try {
        await voiceInFlight;
      } catch {
        /* the racing capture already reported its own error */
      }
    }
    try {
      await bridgeCommand('voice_stop', null);
    } catch {
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
  } finally {
    voiceInFlight = null;
  }
});


// Get voice status.
ipcMain.handle('voice:status', async (): Promise<unknown> => {
  return bridgeCommand('voice_status', null);
});

// Analyze a user-selected / manually entered URL for phishing.
//
// Primary path: FastAPI POST /api/analyze-link {url} — the existing
// link_security engine (never auto-opens the URL). Fallback: the legacy
// bridge `analyze_link` handler (explicit URL first, bounded OCR capture
// only when no URL was passed; never blocks voice).
ipcMain.handle('link:analyze', async (_event, url: string): Promise<unknown> => {
  const target = typeof url === 'string' ? url.trim() : '';
  if (backendReady()) {
    // FastAPI validates + analyzes the exact input; on failure surface the
    // backend's own error (missing-URL vs analysis error stay distinct).
    return backendCall('POST', '/api/analyze-link', { url: target });
  }
  return bridgeCommand('analyze_link', target);
});

// Remember something.
ipcMain.handle('memory:remember', async (_event, key: string, value: string): Promise<unknown> => {
  if (backendReady()) {
    return backendCall('POST', '/api/memory/remember', { key, value });
  }
  return bridgeCommand('remember', { key, value });
});

// Recall something.
ipcMain.handle('memory:recall', async (_event, key: string): Promise<unknown> => {
  if (backendReady()) {
    const body = (await backendCall('POST', '/api/memory/recall', { key })) as {
      data?: string | null;
    };
    return body?.data ?? null;
  }
  return bridgeCommand('recall', key);
});

// System Monitor metrics.
ipcMain.handle('system:metrics', async (): Promise<unknown> => {
  if (backendReady()) {
    return backendCall('GET', '/api/system/metrics');
  }
  return bridgeCommand('system_metrics', null);
});

// Get available commands list
ipcMain.handle('commands:list', async () => {
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
ipcMain.handle('backend:status', () => backendService?.getStatus() ?? null);

// Recent backend stdout/stderr, for the failure panel.
ipcMain.handle('backend:logs', () => backendService?.getLogs() ?? []);

// Retry backend startup (surfaced by the UI Retry button).
ipcMain.handle('backend:restart', async () => {
  if (!backendService) return null;
  dashboardLoaded = false;
  return backendService.retry();
});

// Call the existing FastAPI API on the renderer's behalf.
ipcMain.handle(
  'backend:request',
  async (_event, method: string, apiPath: string, payload?: unknown) => {
    if (!backendService) {
      return { ok: false, status: 0, body: null, error: 'Backend not initialised' };
    }
    return backendService.request(method, apiPath, payload);
  },
);

// Open the existing React desktop UI in its own window.
ipcMain.handle('ui:open-desktop', () => {
  openDesktopUiWindow();
  return true;
});


