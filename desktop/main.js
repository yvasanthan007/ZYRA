/**
 * ZYRA Desktop — native desktop window shell (Electron).
 *
 * Loads the ZYRA dashboard URL (passed by python main.py via the ZYRA_URL
 * environment variable) in a native desktop window instead of a web browser.
 *
 * Secure defaults: contextIsolation, sandbox, no nodeIntegration.
 * Single-instance: a second "open dashboard" just focuses the existing window.
 */

const { app, BrowserWindow, shell, session } = require("electron");
const path = require("path");

const ZYRA_URL = process.env.ZYRA_URL || "http://127.0.0.1:8080";

let mainWindow = null;

// Single-instance lock: repeated launches focus the existing window
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  function createWindow() {
    mainWindow = new BrowserWindow({
      width: 1440,
      height: 900,
      minWidth: 1024,
      minHeight: 700,
      title: "ZYRA",
      backgroundColor: "#000000",
      icon: path.join(__dirname, "icon.ico"),
      show: false,
      autoHideMenuBar: true,
      webPreferences: {
        preload: path.join(__dirname, "preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    });

    mainWindow.loadURL(ZYRA_URL);

    // Open external links in the system browser, never inside the shell
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
      if (!url.startsWith(ZYRA_URL)) {
        shell.openExternal(url);
        return { action: "deny" };
      }
      return { action: "allow" };
    });

    mainWindow.webContents.on("will-navigate", (event, url) => {
      if (!url.startsWith(ZYRA_URL)) {
        event.preventDefault();
        shell.openExternal(url);
      }
    });

    mainWindow.once("ready-to-show", () => {
      mainWindow.show();
      mainWindow.focus();
    });

    mainWindow.on("closed", () => {
      mainWindow = null;
    });
  }

  app.whenReady().then(() => {
    // Permission policy: allow microphone for dashboard voice, deny the rest
    session.defaultSession.setPermissionRequestHandler(
      (_webContents, permission, callback) => {
        callback(permission === "media");
      }
    );

    // Evict any stale HTTP-cached dashboard so a UI update (e.g. the Settings
    // panel) is never shadowed by the shell's persistent disk cache.
    // Clears ONLY the HTTP cache — localStorage settings are untouched.
    session.defaultSession.clearCache().then(() => {
      createWindow();
    });
  });

  app.on("window-all-closed", () => {
    app.quit();
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
}