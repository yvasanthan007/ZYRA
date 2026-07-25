import { app, BrowserWindow, ipcMain } from 'electron';
import * as path from 'path';
import { PythonBridge } from './python-bridge';

let mainWindow: BrowserWindow | null = null;
let pythonBridge: PythonBridge | null = null;

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

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  createWindow();

  // Initialize Python bridge
  pythonBridge = new PythonBridge();
  pythonBridge.start();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
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

// IPC Handlers

// Send message to Python AI
ipcMain.handle('ai:chat', async (_event, message: string) => {
  if (!pythonBridge) return 'Error: Python bridge not initialized';
  return pythonBridge.sendCommand({ type: 'chat', data: message });
});

// Execute a system command
ipcMain.handle('command:execute', async (_event, command: string) => {
  if (!pythonBridge) return 'Error: Python bridge not initialized';
  return pythonBridge.sendCommand({ type: 'command', data: command });
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
