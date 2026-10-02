/**
 * Window-control IPC handlers shared by the real main process and the
 * offscreen verify helper, so tests exercise production code paths.
 */
'use strict';

const { BrowserWindow, ipcMain } = require('electron');

function isMaximized(win) {
  try {
    return win ? win.isMaximized() : false;
  } catch (_) {
    return false;
  }
}

function sendMaximizedState(win) {
  if (!win || win.isDestroyed()) return;
  win.webContents.send('zyra-window:maximized-changed', isMaximized(win));
}

function registerWindowControls(getFallbackWindow) {
  const pick = (event) => {
    try {
      return BrowserWindow.fromWebContents(event.sender) || (getFallbackWindow ? getFallbackWindow() : null);
    } catch (_) {
      return getFallbackWindow ? getFallbackWindow() : null;
    }
  };
  ipcMain.handle('zyra-window:minimize', (event) => {
    const win = pick(event);
    if (win) win.minimize();
  });
  ipcMain.handle('zyra-window:maximize', (event) => {
    const win = pick(event);
    if (win) {
      if (win.isMaximized()) win.unmaximize();
      else win.maximize();
    }
  });
  ipcMain.handle('zyra-window:restore', (event) => {
    const win = pick(event);
    if (win && win.isMaximized()) win.unmaximize();
  });
  ipcMain.handle('zyra-window:close', (event) => {
    const win = pick(event);
    if (win) win.close();
  });
  ipcMain.handle('zyra-window:is-maximized', (event) => {
    return isMaximized(pick(event));
  });
}

module.exports = { isMaximized, sendMaximizedState, registerWindowControls };
