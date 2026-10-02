/**
 * BackendManager: keep the EXISTING FastAPI architecture untouched.
 *
 * Dev: attach to http://127.0.0.1:8080 (started via `npm run web:server` or
 * `npm run dev` which launches both together). No backend process is spawned.
 *
 * Prod (packaged): spawn the bundled backend sidecar and wait for /api/health:
 *   1. resources/backend/ZYRA-backend.exe (PyInstaller output), else
 *   2. `python -m uvicorn backend.server:app` from resources/app.
 */
'use strict';

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 8080;

function httpGetJson(url, timeoutMs = 2500) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      let raw = '';
      res.on('data', (chunk) => { raw += chunk; });
      res.on('end', () => {
        try {
          resolve(JSON.parse(raw));
        } catch (err) {
          reject(err);
        }
      });
    });
    req.on('error', reject);
    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error('health-check timeout'));
    });
  });
}

class BackendManager {
  constructor({ devUrl, isDev }) {
    this.isDev = !!isDev;
    this.baseUrl = devUrl || `http://${DEFAULT_HOST}:${DEFAULT_PORT}`;
    this.child = null;
  }

  getUrl() {
    return this.baseUrl;
  }

  async ensureBackend() {
    if (this.isDev) {
      await this.waitForReady(this.baseUrl, 60000);
      return this.baseUrl;
    }
    // Production: find a free port, then spawn the sidecar on it.
    const port = await this.findFreePort(DEFAULT_PORT);
    this.baseUrl = `http://${DEFAULT_HOST}:${port}`;
    this.spawnSidecar(port);
    await this.waitForReady(this.baseUrl, 90000);
    return this.baseUrl;
  }

  findFreePort(startPort) {
    const net = require('net');
    return new Promise((resolve) => {
      const tryPort = (port) => {
        const server = net.createServer();
        server.once('error', () => tryPort(port + 1));
        server.once('listening', () => {
          server.close(() => resolve(port));
        });
        server.listen(port, DEFAULT_HOST);
      };
      tryPort(startPort);
    });
  }

  resolveSidecar() {
    // 1) PyInstaller one-dir / one-file backend next to resources.
    const candidates = [
      path.join(process.resourcesPath || '', 'backend', process.platform === 'win32' ? 'ZYRA-backend.exe' : 'ZYRA-backend'),
      path.join(process.resourcesPath || '', 'ZYRA-backend.exe'),
    ];
    for (const candidate of candidates) {
      try {
        if (candidate && fs.existsSync(candidate)) return { kind: 'binary', cmd: candidate, args: [] };
      } catch (_) { /* ignore */ }
    }
    // 2) Fall back to system python running the bundled sources.
    const appRoot = path.join(__dirname, '..');
    const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';
    return {
      kind: 'python',
      cmd: pythonCmd,
      args: ['-m', 'uvicorn', 'backend.server:app', '--host', DEFAULT_HOST, '--port', String(this.portFromUrl())],
      cwd: appRoot,
    };
  }

  portFromUrl() {
    try {
      return Number(new URL(this.baseUrl).port) || DEFAULT_PORT;
    } catch (_) {
      return DEFAULT_PORT;
    }
  }

  spawnSidecar(port) {
    const sidecar = this.resolveSidecar();
    const env = { ...process.env, ZYRA_BACKEND_PORT: String(port), PORT: String(port) };
    try {
      if (sidecar.kind === 'binary') {
        this.child = spawn(sidecar.cmd, ['--port', String(port)], { env, windowsHide: true });
      } else {
        this.child = spawn(sidecar.cmd, sidecar.args, { cwd: sidecar.cwd, env, windowsHide: true });
      }
      if (this.child && this.child.stdout) {
        this.child.stdout.on('data', (d) => process.stdout.write(`[zyra-backend] ${d}`));
      }
      if (this.child && this.child.stderr) {
        this.child.stderr.on('data', (d) => process.stderr.write(`[zyra-backend] ${d}`));
      }
      if (this.child) {
        this.child.on('exit', (code) => {
          console.log(`[zyra] backend sidecar exited with code ${code}`);
        });
      }
    } catch (err) {
      console.error('[zyra] failed to spawn backend sidecar:', err && err.message);
      throw err;
    }
  }

  async waitForReady(baseUrl, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    let lastErr = null;
    while (Date.now() < deadline) {
      try {
        const health = await httpGetJson(`${baseUrl}/api/health`, 2500);
        if (health) return true;
      } catch (err) {
        lastErr = err;
      }
      await new Promise((r) => setTimeout(r, 750));
    }
    throw lastErr || new Error('backend health check timed out');
  }

  async stop() {
    this.stopSync();
  }

  stopSync() {
    try {
      if (this.child && !this.child.killed) {
        if (process.platform === 'win32') {
          try {
            // Best-effort tree kill on Windows so uvicorn children die too.
            require('child_process').execSync(`taskkill /PID ${this.child.pid} /T /F`, { stdio: 'ignore' });
          } catch (_) {
            try { this.child.kill(); } catch (_) { /* ignore */ }
          }
        } else {
          try { this.child.kill('SIGTERM'); } catch (_) { /* ignore */ }
        }
      }
    } catch (_) { /* ignore */ }
    this.child = null;
  }
}

module.exports = { BackendManager };
