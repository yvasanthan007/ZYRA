/**
 * ZYRA Desktop — native desktop window shell (Electron).
 *
 * Wraps the EXISTING ZYRA web application without modifying it:
 *   1. Spawns the existing Python entry point (main.py) using the project's
 *      own virtual environment, with ZYRA_DESKTOP=1 so main.py skips its
 *      Edge-kiosk browser launch (the desktop window replaces the browser).
 *   2. Polls the existing backend health endpoint until ZYRA is ready.
 *   3. Opens a native desktop window that loads http://127.0.0.1:8080 —
 *      the exact same dashboard the browser shows today.
 *   4. On shutdown, kills the spawned Python process tree cleanly.
 *
 * Secure defaults: contextIsolation, sandbox, no nodeIntegration. No Node
 * APIs are exposed to the renderer; all functionality comes from the
 * existing ZYRA backend over HTTP/WebSocket exactly as in the browser.
 */

const { app, BrowserWindow, shell, session } = require("electron");
const { spawn, exec } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

const ZYRA_HOST = process.env.ZYRA_SERVER_HOST || "127.0.0.1";
const ZYRA_PORT = parseInt(process.env.ZYRA_SERVER_PORT || "8080", 10);
const ZYRA_URL = `http://${ZYRA_HOST}:${ZYRA_PORT}`;

// Project root = parent of the desktop/ folder
const ZYRA_ROOT = path.join(__dirname, "..");

let mainWindow = null;
let zyraProcess = null;
let shuttingDown = false;

// ─────────────────────────────────────────────────────────────────────
// Python process management
// ─────────────────────────────────────────────────────────────────────

function findPythonExecutable() {
  // 1. Explicit override (ZYRA_PYTHON env var)
  if (process.env.ZYRA_PYTHON && fs.existsSync(process.env.ZYRA_PYTHON)) {
    return process.env.ZYRA_PYTHON;
  }

  const candidates = [];

  if (app.isPackaged) {
    // Packaged mode: the ZYRA source (and optionally a bundled Python venv
    // or portable runtime) lives in <resources>/zyra
    const res = path.join(process.resourcesPath, "zyra");
    candidates.push(path.join(res, ".venv", "Scripts", "pythonw.exe"));
    candidates.push(path.join(res, ".venv", "Scripts", "python.exe"));
    candidates.push(path.join(res, "python", "pythonw.exe"));
    candidates.push(path.join(res, "python", "python.exe"));
  }

  // Development mode (and dev-machine fallback): the project's own venv —
  // exactly what `python main.py` uses today.
  candidates.push(path.join(ZYRA_ROOT, ".venv", "Scripts", "pythonw.exe"));
  candidates.push(path.join(ZYRA_ROOT, ".venv", "Scripts", "python.exe"));

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }

  return "python";
}

// Where main.py lives: project root in dev, <resources>/zyra when packaged
function zyraSourceRoot() {
  if (app.isPackaged) {
    const res = path.join(process.resourcesPath, "zyra");

    if (fs.existsSync(path.join(res, "main.py"))) {
      return res;
    }
  }

  return ZYRA_ROOT;
}

function startZyra() {
  const pythonExe = findPythonExecutable();

  console.log(`[ZYRA Desktop] Starting ZYRA backend: ${pythonExe} main.py`);

  zyraProcess = spawn(pythonExe, ["main.py"], {
    cwd: zyraSourceRoot(),

    env: {
      ...process.env,
      ZYRA_DESKTOP: "1",
      PYTHONIOENCODING: "utf-8",
      PYTHONUTF8: "1",
    },

    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });

  // Surface backend logs in the desktop terminal for diagnostics
  const log = (buf) => process.stdout.write(buf.toString());

  zyraProcess.stdout?.on("data", log);
  zyraProcess.stderr?.on("data", log);

  zyraProcess.on("exit", (code) => {
    console.log(`[ZYRA Desktop] ZYRA backend exited (code ${code})`);

    zyraProcess = null;

    // If the backend dies unexpectedly, close the window so the user
    // isn't left staring at a dead dashboard.
    if (!shuttingDown && mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.close();
    }
  });

  zyraProcess.on("error", (err) => {
    console.error(
      `[ZYRA Desktop] Failed to start ZYRA backend: ${err.message}`
    );
  });
}

function stopZyra() {
  if (shuttingDown) return;

  shuttingDown = true;

  if (zyraProcess && !zyraProcess.killed) {
    const pid = zyraProcess.pid;

    console.log(
      `[ZYRA Desktop] Shutting down ZYRA backend (pid ${pid})...`
    );

    try {
      if (process.platform === "win32") {
        // taskkill /T kills the whole tree (uvicorn thread + any children)
        exec(`taskkill /PID ${pid} /T /F`, {
          windowsHide: true,
        });
      } else {
        zyraProcess.kill("SIGTERM");
      }
    } catch (err) {
      console.error(
        `[ZYRA Desktop] Shutdown error: ${err.message}`
      );
    }
  }
}

// ─────────────────────────────────────────────────────────────────────
// Health polling — wait until the existing backend is ready
// ─────────────────────────────────────────────────────────────────────

function isBackendReady() {
  return new Promise((resolve) => {
    const req = http.get(
      `${ZYRA_URL}/api/health`,
      { timeout: 2000 },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      }
    );

    req.on("error", () => resolve(false));

    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForBackend(maxSeconds = 90) {
  const deadline = Date.now() + maxSeconds * 1000;

  while (Date.now() < deadline) {
    if (await isBackendReady()) {
      return true;
    }

    await new Promise((r) => setTimeout(r, 500));
  }

  return false;
}

// ─────────────────────────────────────────────────────────────────────
// Window
// ─────────────────────────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,

    minWidth: 1024,
    minHeight: 700,

    title: "ZYRA",
    backgroundColor: "#000000",

    icon: path.join(__dirname, "zyra.ico"),

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

  mainWindow.setMenuBarVisibility(false);

  mainWindow.loadURL(ZYRA_URL);

  // Open external links in the system browser, never inside the shell
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(ZYRA_URL)) {
      shell.openExternal(url);

      return {
        action: "deny",
      };
    }

    return {
      action: "allow",
    };
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

// ─────────────────────────────────────────────────────────────────────
// App lifecycle
// ─────────────────────────────────────────────────────────────────────

const gotLock = app.requestSingleInstanceLock();

if (!gotLock) {
  app.quit();
} else {
  // External mode: this shell was launched BY an existing ZYRA backend
  // (python main.py). The backend is already running — the shell must NOT
  // spawn its own Python, and closing the window stops that parent process.
  const externalShellMode =
    process.env.ZYRA_EXTERNAL_SHELL === "1";

  // Single-instance behavior
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }

      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    // Permission policy: allow microphone for the dashboard voice features,
    // deny everything else (no geolocation, notifications, etc.).
    session.defaultSession.setPermissionRequestHandler(
      (_webContents, permission, callback) => {
        callback(permission === "media");
      }
    );

    if (!externalShellMode) {
      startZyra();
    }

    console.log(
      "[ZYRA Desktop] Waiting for ZYRA backend to become ready..."
    );

    const ready = await waitForBackend(
      externalShellMode ? 20 : 90
    );

    if (!ready) {
      console.error(
        "[ZYRA Desktop] ZYRA backend did not become ready in time — opening the window anyway."
      );
    }

    createWindow();
  });

  app.on("window-all-closed", () => {
    if (
      externalShellMode &&
      process.env.ZYRA_PARENT_PID
    ) {
      // The backend belongs to the parent python process. Closing the
      // desktop window shuts the whole ZYRA application down.
      const parentPid = parseInt(
        process.env.ZYRA_PARENT_PID,
        10
      );

      if (parentPid) {
        console.log(
          `[ZYRA Desktop] Window closed — stopping ZYRA backend (pid ${parentPid})...`
        );

        try {
          exec(
            `taskkill /PID ${parentPid} /T /F`,
            {
              windowsHide: true,
            }
          );
        } catch (err) {
          console.error(
            `[ZYRA Desktop] Failed to stop backend: ${err.message}`
          );
        }
      }

      setTimeout(() => app.quit(), 300);
    } else {
      stopZyra();

      // Give the backend a moment to die, then quit.
      setTimeout(() => app.quit(), 500);
    }
  });

  app.on("before-quit", () => {
    stopZyra();
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
}