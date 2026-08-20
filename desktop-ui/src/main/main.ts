import { app, BrowserWindow, ipcMain, Tray, Menu, Notification } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import log from 'electron-log';
import { autoUpdater } from 'electron-updater';
import { PythonBridge } from './python-bridge';

let mainWindow: BrowserWindow | null = null;
let pythonBridge: PythonBridge | null = null;
let tray: Tray | null = null;

// ── Configure logging ──────────────────────────────────────
log.transports.file.level = 'info';
autoUpdater.logger = log;

// ── Native Application Menu ────────────────────────────────
function createMenu(mainWindow: BrowserWindow): void {
  const isMac = process.platform === 'darwin';
  const template: (Electron.MenuItemConstructor | Electron.SubmenuItemConstructor)[] = [
    // macOS app menu
    ...(isMac ? [{
      label: app.getName(),
      submenu: [
        { label: 'About ZYRA', role: 'about' },
        { type: 'separator' as const },
        { label: 'Preferences…', accelerator: 'Cmd+,', role: 'reload' },
        { type: 'separator' as const },
        { label: 'Quit', accelerator: 'Cmd+Q', role: 'quit' },
      ],
    }] : []),
    // File menu
    {
      label: 'File',
      submenu: [
        isMac && { label: 'Close Window', accelerator: 'Cmd+W', role: 'closeWindow' },
        { label: 'Exit', role: 'quit' },
      ].filter(Boolean) as Electron.MenuItemConstructor[],
    },
    // Edit menu
    {
      label: 'Edit',
      submenu: [
        { label: 'Undo', accelerator: 'CmdOrCtrl+Z', role: 'undo' },
        { label: 'Redo', accelerator: 'CmdOrCtrl+Shift+Z', role: 'redo' },
        { type: 'separator' as const },
        { label: 'Cut', accelerator: 'CmdOrCtrl+X', role: 'cut' },
        { label: 'Copy', accelerator: 'CmdOrCtrl+C', role: 'copy' },
        { label: 'Paste', accelerator: 'CmdOrCtrl+V', role: 'paste' },
        { type: 'separator' as const },
        { label: 'Select All', accelerator: 'CmdOrCtrl+A', role: 'selectAll' },
      ],
    },
    // ZYRA custom menu
    {
      label: 'ZYRA',
      submenu: [
        {
          label: 'Open Dashboard',
          click: () => { mainWindow.show(); mainWindow.webContents.send('navigate:chat'); },
        },
        {
          label: 'Voice Assistant',
          accelerator: 'CmdOrCtrl+Shift+V',
          click: async () => {
            try { await mainWindow.webContents.invoke('voice:toggle', true); }
            catch (e) { log.error('Voice toggle failed:', e); }
          },
        },
        { type: 'separator' as const },
        { label: 'Check for Updates…', click: () => mainWindow.webContents.send('app:update-check') },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template as any));
}

// ── System Tray ────────────────────────────────────────────
function createTray(mainWindow: BrowserWindow): void {
  let iconPath = path.join(__dirname, '../build/icons/tray-icon.png');
  if (!fs.existsSync(iconPath)) {
    iconPath = path.join(__dirname, '../build/icons/icon.png');
  }
  tray = new Tray(iconPath);
  tray.setToolTip('ZYRA — AI Assistant');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show ZYRA', click: () => { mainWindow.show(); } },
    { type: 'separator' },
    { label: 'Quick Chat', click: () => { mainWindow.show(); mainWindow.webContents.send('voice:start'); } },
    { type: 'separator' },
    { label: 'Quit', click: () => { pythonBridge?.stop(); app.quit(); } },
  ]));
  tray.on('click', () => {
    if (mainWindow.isVisible()) mainWindow.hide();
    else mainWindow.show();
  });
}

// ── Auto-Updater ───────────────────────────────────────────
function initAutoUpdater(mainWindow: BrowserWindow): void {
  if (!app.isPackaged) { log.info('Auto-updater skipped in dev'); return; }
  autoUpdater.checkForUpdatesAndNotify();
  autoUpdater.on('update-available', (info) => mainWindow.webContents.send('app:update-available', info));
  autoUpdater.on('update-downloaded', (info) => mainWindow.webContents.send('app:update-downloaded', info));
  autoUpdater.on('error', (err) => log.error('Update error:', err));
  autoUpdater.on('download-progress', (p) => log.info(`Download ${Math.round(p.percent)}%`));
}

// ── File System & App IPC Handlers ─────────────────────────
ipcMain.handle('fs:save-conversation', async (_event, data: any) => {
  const file = path.join(app.getPath('userData'), 'conversations.json');
  try { fs.writeFileSync(file, JSON.stringify(data, null, 2)); return file; }
  catch (e) { log.error('Save conversation failed:', e); throw e; }
});

ipcMain.handle('fs:load-conversation', async () => {
  const file = path.join(app.getPath('userData'), 'conversations.json');
  try { return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf-8')) : null; }
  catch (e) { log.error('Load conversation failed:', e); return null; }
});

ipcMain.handle('fs:select-directory', async () => {
  if (!mainWindow) return null;
  const { dialog } = require('electron');
  const result = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory'] });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('app:notification', (_event, title: string, body: string) => {
  new Notification({ title, body }).show();
});

ipcMain.handle('app:quit-and-install', () => {
  autoUpdater.quitAndInstall(false, true);
});

// ── Window Creation ────────────────────────────────────────
function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'ZYRA - AI Assistant',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  // Open DevTools in development
  if (!app.isPackaged) {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // On macOS, hide instead of close (Cmd+W behavior)
  mainWindow.on('close', (event) => {
    if (process.platform === 'darwin' && !event.defaultPrevented) {
      event.preventDefault();
      mainWindow?.hide();
    }
  });
}

app.whenReady().then(() => {
  createWindow();

  if (mainWindow) {
    createMenu(mainWindow);
    createTray(mainWindow);
    initAutoUpdater(mainWindow);
  }

  // Initialize Python bridge
  pythonBridge = new PythonBridge();
  pythonBridge.start();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    } else {
      mainWindow?.show();
    }
  });
});

app.on('window-all-closed', () => {
  if (pythonBridge) {
    pythonBridge.stop();
  }
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  if (pythonBridge) {
    pythonBridge.stop();
  }
});

// IPC Handlers

// Send message to Python AI
ipcMain.handle('ai:chat', async (_event, message: string) => {
  if (!pythonBridge) return 'Error: Python bridge not initialized';
  try {
    return await pythonBridge.sendCommand({ type: 'chat', data: message });
  } catch (e) {
    log.error('AI chat error:', e);
    return 'Error: Failed to communicate with AI. Please try again.';
  }
});

// Execute a system command
ipcMain.handle('command:execute', async (_event, command: string) => {
  if (!pythonBridge) return 'Error: Python bridge not initialized';
  try {
    return await pythonBridge.sendCommand({ type: 'command', data: command });
  } catch (e) {
    log.error('Command execution error:', e);
    return 'Error: Command execution failed.';
  }
});

// Toggle voice listening
ipcMain.handle('voice:toggle', async (_event, enabled: boolean) => {
  if (!pythonBridge) return 'Error: Python bridge not initialized';
  return pythonBridge.sendCommand({ type: 'voice_toggle', data: enabled });
});

// Get voice status
ipcMain.handle('voice:status', async () => {
  if (!pythonBridge) return { listening: false };
  return pythonBridge.sendCommand({ type: 'voice_status', data: null });
});

// Remember something
ipcMain.handle('memory:remember', async (_event, key: string, value: string) => {
  if (!pythonBridge) return 'Error: Python bridge not initialized';
  return pythonBridge.sendCommand({ type: 'remember', data: { key, value } });
});

// Recall something
ipcMain.handle('memory:recall', async (_event, key: string) => {
  if (!pythonBridge) return null;
  return pythonBridge.sendCommand({ type: 'recall', data: key });
});

// Get available commands list — try bridge first, fall back to static list
ipcMain.handle('commands:list', async () => {
  if (!pythonBridge) {
    return [
      { id: 'open_chrome', label: 'Open Chrome', category: 'apps' },
      { id: 'open_vscode', label: 'Open VS Code', category: 'apps' },
      { id: 'open_notepad', label: 'Open Notepad', category: 'apps' },
      { id: 'open_calculator', label: 'Open Calculator', category: 'apps' },
      { id: 'open_google', label: 'Open Google', category: 'web' },
      { id: 'open_youtube', label: 'Open YouTube', category: 'web' },
      { id: 'open_github', label: 'Open GitHub', category: 'web' },
      { id: 'volume_up', label: 'Volume Up', category: 'system' },
      { id: 'volume_down', label: 'Volume Down', category: 'system' },
      { id: 'mute', label: 'Mute', category: 'system' },
      { id: 'screenshot', label: 'Screenshot', category: 'system' },
      { id: 'lock_pc', label: 'Lock PC', category: 'system' },
      { id: 'shutdown', label: 'Shutdown', category: 'system' },
      { id: 'current_time', label: 'Current Time', category: 'info' },
      { id: 'current_date', label: 'Current Date', category: 'info' },
      { id: 'play_music', label: 'Play Music', category: 'media' },
      { id: 'open_camera', label: 'Open Camera', category: 'media' },
    ];
  }
  try {
    return await pythonBridge.sendCommand({ type: 'list_commands', data: null });
  } catch {
    return []; // Graceful fallback
  }
});

// Text-to-speech
ipcMain.handle('app:speak', async (_event, text: string) => {
  if (!pythonBridge) return 'Error: Python bridge not initialized';
  return pythonBridge.sendCommand({ type: 'speak', data: text });
});

// Analyze link security
ipcMain.handle('security:analyze-link', async (_event, data: string | { url: string }) => {
  if (!pythonBridge) return { success: false, error: 'Python bridge not initialized' };
  const url = typeof data === 'string' ? data : data.url;
  return pythonBridge.sendCommand({ type: 'analyze_link', data: url });
});
