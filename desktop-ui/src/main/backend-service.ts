import { EventEmitter } from 'events';
import { spawn, spawnSync, ChildProcess } from 'child_process';
import * as http from 'http';
import * as path from 'path';
import { resolveBackendLaunch } from './zyra-paths';

/**
 * backend-service.ts — owns the FastAPI backend that powers the ZYRA dashboard.
 *
 * The desktop shell starts ZYRA's existing backend (`main.py`) as a child
 * process with `ZYRA_NO_EDGE=1`, so the FastAPI server + WebSocket come up
 * exactly as they always have, but without opening the external Edge kiosk
 * window. This class only *manages* that process — it never changes any ZYRA
 * API contract or security engine.
 */

export type BackendState = 'idle' | 'starting' | 'ready' | 'failed' | 'stopped';

export interface BackendStatus {
  state: BackendState;
  /** Base URL of the FastAPI backend, e.g. http://127.0.0.1:8080 */
  url: string | null;
  host: string;
  port: number | null;
  /** PID of the process *we* spawned (null when we adopted an existing one). */
  pid: number | null;
  /** True when Electron started the process and is therefore responsible for it. */
  managedByElectron: boolean;
  /** True when an already-running ZYRA backend was reused instead of spawning. */
  adopted: boolean;
  error: string | null;
  /** How long startup took, in milliseconds. */
  startupMs: number | null;
  /** Interpreter actually used, for diagnostics. */
  interpreter: string | null;
}

/** Result of a renderer-initiated call to the existing FastAPI API. */
export interface BackendRequestResult {
  ok: boolean;
  status: number;
  body: unknown;
  error: string | null;
}

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 8080;
const STARTUP_TIMEOUT_MS = 45000;
const POLL_INTERVAL_MS = 500;
const LOG_LIMIT = 400;

// uvicorn / Windows socket errors emitted when the port is already taken.
const BIND_ERROR_RE =
  /address already in use|error while attempting to bind|only one usage of each socket address|WinError 10048|Errno 10048/i;

export class BackendService extends EventEmitter {
  private proc: ChildProcess | null = null;
  private managedByElectron = false;
  /** First bind-failure line seen from the child, if any (port conflict). */
  private bindError: string | null = null;
  private logs: string[] = [];
  private status: BackendStatus;

  private readonly host: string;
  private readonly port: number;

  constructor(host: string = DEFAULT_HOST, port: number = DEFAULT_PORT) {
    super();
    this.host = host;
    this.port = port;
    this.status = this.blankStatus();
  }

  private blankStatus(): BackendStatus {
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

  getStatus(): BackendStatus {
    return { ...this.status };
  }

  /** Most recent backend stdout/stderr lines, newest last. */
  getLogs(): string[] {
    return this.logs.slice();
  }

  // ── lifecycle ─────────────────────────────────────────────────────────────

  /**
   * Start (or adopt) the backend.
   *
   * Never throws: failures are reported through the returned status so the UI
   * can render them instead of dying with an unhandled rejection.
   */
  async start(): Promise<BackendStatus> {
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
      return this.fail(
        `Port ${this.port} is in use by a service that is not the ZYRA backend. ` +
          `Close the program using port ${this.port} (or free it) and retry.`,
      );
    }

    return this.spawnBackend(startedAt);
  }

  private async spawnBackend(startedAt: number): Promise<BackendStatus> {
    this.bindError = null;

    // One resolution covers both modes: the bundled PyInstaller executable in an
    // installed build, or a Python interpreter running main.py in development.
    let launch;
    try {
      launch = resolveBackendLaunch();
    } catch (err) {
      return this.fail(`Could not locate the ZYRA backend: ${String(err)}`);
    }

    this.recordLog(`desktop: launching backend -> ${launch.display}`);
    this.update({
      interpreter: launch.display,
      adopted: false,
      managedByElectron: true,
    });

    try {
      this.proc = spawn(launch.command, launch.args, {
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
    } catch (err) {
      return this.fail(`Failed to launch the ZYRA backend (${launch.display}): ${String(err)}`);
    }

    const child = this.proc;
    child.stdout?.on('data', (data: Buffer) => this.recordLog(data.toString()));
    child.stderr?.on('data', (data: Buffer) => this.recordLog(data.toString()));
    child.on('error', (err: Error) => {
      this.fail(`Python process error: ${err.message}`);
    });
    child.on('exit', (code: number | null) => {
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
        return this.fail(
          `Port ${this.port} is already in use, so the ZYRA backend could not start. ` +
            `Close the program using port ${this.port} and retry. ` +
            `(${this.bindError})`,
        );
      }
      const tail = this.logs.slice(-6).join(' | ');
      return this.fail(
        `The ZYRA backend did not become ready within ${STARTUP_TIMEOUT_MS / 1000}s.` +
          (tail ? ` Recent output: ${tail}` : ''),
      );
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
  async request(method: string, apiPath: string, payload?: unknown): Promise<BackendRequestResult> {
    const url = this.status.url;
    if (!url) {
      return { ok: false, status: 0, body: null, error: 'Backend is not ready' };
    }
    const target = new URL(apiPath, url);
    const body = payload === undefined ? null : Buffer.from(JSON.stringify(payload), 'utf-8');

    return new Promise<BackendRequestResult>((resolve) => {
      const req = http.request(
        {
          hostname: target.hostname,
          port: target.port,
          path: target.pathname + target.search,
          method,
          headers: body
            ? { 'Content-Type': 'application/json', 'Content-Length': body.length }
            : undefined,
          timeout: 30000,
        },
        (res) => {
          const chunks: Buffer[] = [];
          res.on('data', (chunk: Buffer) => chunks.push(chunk));
          res.on('end', () => {
            const text = Buffer.concat(chunks).toString('utf-8');
            let parsed: unknown = text;
            try {
              parsed = JSON.parse(text);
            } catch {
              /* leave as text */
            }
            const status = res.statusCode ?? 0;
            resolve({ ok: status >= 200 && status < 300, status, body: parsed, error: null });
          });
        },
      );
      req.on('timeout', () => req.destroy(new Error('Request timed out')));
      req.on('error', (err: Error) =>
        resolve({ ok: false, status: 0, body: null, error: err.message }),
      );
      if (body) req.write(body);
      req.end();
    });
  }

  /** Re-attempt startup after a failure (surfaced by the UI Retry button). */
  async retry(): Promise<BackendStatus> {
    this.killOwnedProcess();
    return this.start();
  }

  /**
   * Public shutdown entry point, called when the app is closing.
   * Only ever terminates a process this instance started; an adopted backend is
   * left running because Electron does not own it.
   */
  async stop(): Promise<void> {
    this.killOwnedProcess();
    this.update({ state: 'stopped', pid: null });
  }

  /** Synchronous best-effort reap for process.on('exit'). */
  forceKillSync(): void {
    if (this.proc && this.managedByElectron && typeof this.proc.pid === 'number') {
      this.killTreeSync(this.proc.pid);
      this.proc = null;
    }
  }

  isRunning(): boolean {
    return this.status.state === 'ready';
  }

  // ── internals ────────────────────────────────────────────────────────────

  private update(patch: Partial<BackendStatus>): void {
    this.status = { ...this.status, ...patch };
    this.emit('status', this.getStatus());
  }

  private fail(message: string): BackendStatus {
    this.recordLog(`desktop: ${message}`);
    this.update({ state: 'failed', error: message, startupMs: null });
    return this.getStatus();
  }

  private recordLog(chunk: string): void {
    const lines = chunk.split(/\r?\n/);
    for (const line of lines) {
      const trimmed = line.trimEnd();
      if (!trimmed) continue;
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

  private probeHealth(): Promise<{ reachable: boolean; zyra: boolean }> {
    return new Promise((resolve) => {
      const req = http.request(
        {
          hostname: this.host,
          port: this.port,
          path: '/api/health',
          method: 'GET',
          timeout: 2500,
        },
        (res) => {
          const chunks: Buffer[] = [];
          res.on('data', (chunk: Buffer) => chunks.push(chunk));
          res.on('end', () => {
            let zyra = false;
            try {
              const parsed = JSON.parse(Buffer.concat(chunks).toString('utf-8')) as {
                zyra?: string;
                version?: string;
              };
              // Require ZYRA's own sentinel field. A generic {"status":"ok"}
              // from an unrelated service on the same port must NOT be mistaken
              // for our backend, or Electron would adopt it and the dashboard
              // would fail to load.
              zyra = parsed.zyra === 'running';
            } catch {
              /* not JSON -> not a ZYRA health payload */
            }
            resolve({ reachable: true, zyra });
          });
        },
      );
      req.on('timeout', () => {
        req.destroy();
        resolve({ reachable: false, zyra: false });
      });
      req.on('error', () => resolve({ reachable: false, zyra: false }));
      req.end();
    });
  }

  /** Poll /api/health until the backend genuinely answers, or we give up. */
  private async pollUntilReady(timeoutMs: number): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      // Definitive bind failure: no point waiting for the full timeout.
      if (this.bindError) return false;
      if (!this.proc && this.status.state === 'failed') return false;
      const health = await this.probeHealth();
      if (health.reachable && health.zyra) return true;
      await this.delay(POLL_INTERVAL_MS);
    }
    return false;
  }

  private delay(ms: number): Promise<void> {
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
  private killOwnedProcess(): void {
    if (!this.proc) return;
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

  private killTreeSync(pid: number): void {
    try {
      if (process.platform === 'win32') {
        spawnSync('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true });
      } else {
        process.kill(pid, 'SIGTERM');
      }
    } catch (err) {
      console.error('Failed to terminate backend process tree:', err);
    }
  }
}
