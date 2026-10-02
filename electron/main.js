/**
 * ZYRA Electron main process.
 *
 * Loads the EXISTING ZYRA web application (FastAPI + desktop-dashboard/index.html)
 * without redesigning it. In dev it attaches to the already-running backend on
 * http://127.0.0.1:8080. In production it spawns the bundled backend sidecar.
 *
 * Security: contextIsolation=true, nodeIntegration=false, sandbox=true.
 * Renderer <-> main communication only via electron/preload.js + IPC whitelist.
 */
'use strict';

const { app, BrowserWindow, shell } = require('electron');
const path = require('path');
const { BackendManager } = require('./backend-manager');
const { loadWindowState, saveWindowState } = require('./window-state');
const { registerDesktopServiceHandlers } = require('./services');
const { setupTitlebarInjection } = require('./titlebar/inject');
const { isMaximized, sendMaximizedState, registerWindowControls } = require('./window-controls');

const DEV_URL = process.env.ZYRA_DEV_URL || 'http://127.0.0.1:8080';
const IS_DEV = !app.isPackaged;

let mainWindow = null;
let backendManager = null;

function createWindow(startUrl) {
  const saved = loadWindowState();

  mainWindow = new BrowserWindow({
    title: 'ZYRA',
    width: saved.width || 1400,
    height: saved.height || 900,
    x: saved.x,
    y: saved.y,
    minWidth: 1000,
    minHeight: 650,
    resizable: true,
    show: false,
    autoHideMenuBar: true,
    frame: false, // custom ZYRA title bar (see electron/titlebar/)
    backgroundColor: '#080812',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  });

  if (saved.maximized) {
    mainWindow.maximize();
  }

  // Keep external links out of the app shell.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url && !url.startsWith('http://127.0.0.1') && !url.startsWith('http://localhost')) {
      shell.openExternal(url).catch(() => {});
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });

  // Running with --headless/--verify renders offscreen for automated checks.
  if (process.argv.includes('--headless') || process.argv.includes('--verify')) {
    try {
      mainWindow.webContents.setBackgroundThrottling(false);
    } catch (_) { /* ignore */ }
  }

  mainWindow.on('maximize', () => {
    sendMaximizedState(mainWindow);
    saveWindowState(mainWindow);
  });
  mainWindow.on('unmaximize', () => {
    sendMaximizedState(mainWindow);
    saveWindowState(mainWindow);
  });
  mainWindow.on('resize', () => {
    if (!isMaximized(mainWindow)) saveWindowState(mainWindow);
  });
  mainWindow.on('move', () => {
    if (!isMaximized(mainWindow)) saveWindowState(mainWindow);
  });
  mainWindow.on('close', () => {
    saveWindowState(mainWindow);
  });
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  setupTitlebarInjection(mainWindow);

  mainWindow.once('ready-to-show', () => {
    if (mainWindow) {
      mainWindow.show();
      sendMaximizedState(mainWindow);
      if (IS_DEV) {
        // Uncomment during UI debugging:
        // mainWindow.webContents.openDevTools({ mode: 'detach' });
      }
    }
  });

  mainWindow.loadURL(startUrl).catch((err) => {
    // Show a recoverable error instead of a blank window.
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.executeJavaScript(
        `document.title='ZYRA - backend unavailable';document.body.innerHTML='<div style="display:flex;height:100vh;align-items:center;justify-content:center;background:#080812;color:#ff8844;font-family:Segoe UI,sans-serif;text-align:center;padding:24px;"><div><h2>ZYRA backend is not reachable</h2><p style="opacity:.8">Expected at ${startUrl}. Start it with <code>npm run web:server</code> then reload.</p></div></div>'`
      ).catch(() => {});
    }
    console.error('[zyra] failed to load backend URL:', err && err.message);
  });

  return mainWindow;
}

// Shared window-control handlers (imported for side-effect-free reuse note).

async function boot() {
  backendManager = new BackendManager({ devUrl: DEV_URL, isDev: IS_DEV });
  registerWindowControls(() => mainWindow);
  registerDesktopServiceHandlers({ backendManager });

  let startUrl = DEV_URL;
  try {
    startUrl = await backendManager.ensureBackend();
  } catch (err) {
    console.error('[zyra] backend did not become ready, loading dev URL anyway:', err && err.message);
    startUrl = backendManager.getUrl();
  }

  createWindow(startUrl);
}

app.whenReady().then(boot).catch((err) => {
  console.error('[zyra] failed to start:', err);
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow(backendManager ? backendManager.getUrl() : DEV_URL);
  }
});

app.on('window-all-closed', () => {
  if (backendManager) {
    backendManager.stop().catch(() => {});
    backendManager = null;
  }
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (backendManager) {
    // Fire-and-forget; BackendManager kills the child synchronously.
    backendManager.stopSync();
  }
});
