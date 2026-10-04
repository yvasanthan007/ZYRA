import * as fs from 'fs';
import * as path from 'path';

/**
 * zyra-paths.ts — desktop path & interpreter resolution for ZYRA.
 *
 * The Electron shell must find two things reliably regardless of where it is
 * launched from: (1) the ZYRA project root and (2) a usable Python interpreter.
 * Nothing here hard-codes an absolute machine-specific path.
 */

export type PythonSource = 'ZYRA_PYTHON' | 'venv' | 'venv-fallback' | 'PATH';
export type BackendSource = 'ZYRA_BACKEND' | 'packaged' | PythonSource;

export interface PythonCommand {
  /** Executable to spawn. */
  command: string;
  /** Where the choice came from — surfaced in logs for debugging. */
  source: PythonSource;
  /** Human readable description of the interpreter that was selected. */
  display: string;
}

/**
 * Everything needed to launch the ZYRA backend, whatever mode we are in.
 *
 * In an installed build this is the bundled PyInstaller executable; in a source
 * checkout it is a Python interpreter plus `main.py`.
 */
export interface BackendLaunch {
  /** Executable to spawn. */
  command: string;
  /** Arguments passed to the executable. */
  args: string[];
  /** Working directory for the child process. */
  cwd: string;
  /** Human readable description, surfaced in logs and the splash screen. */
  display: string;
  /** Where the choice came from. */
  source: BackendSource;
}

/** Electron injects `resourcesPath` at runtime; typed defensively. */
function resourcesPath(): string | null {
  const value = (process as NodeJS.Process & { resourcesPath?: string }).resourcesPath;
  return typeof value === 'string' && value.length > 0 ? value : null;
}

/** A directory counts as the ZYRA project root when both markers exist. */
export function isProjectRoot(dir: string): boolean {
  try {
    return (
      fs.existsSync(path.join(dir, 'main.py')) &&
      fs.existsSync(path.join(dir, 'desktop-dashboard', 'index.html')) &&
      fs.existsSync(path.join(dir, 'backend', 'server.py'))
    );
  } catch {
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
export function resolveProjectRoot(startDir?: string): string {
  const base = startDir || __dirname;

  const packaged = resourcesPath();
  if (packaged) {
    const bundled = path.join(packaged, 'zyra');
    if (isProjectRoot(bundled)) return bundled;
    if (isProjectRoot(packaged)) return packaged;
  }

  let dir = base;
  for (let i = 0; i < 8; i += 1) {
    if (isProjectRoot(dir)) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) break;
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
export function resolvePython(root: string): PythonCommand {
  const override = process.env.ZYRA_PYTHON;
  if (override && override.trim().length > 0) {
    const command = override.trim();
    return { command, source: 'ZYRA_PYTHON', display: command };
  }

  const isWindows = process.platform === 'win32';
  const candidates: Array<{ file: string; source: PythonSource }> = isWindows
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
    } catch {
      /* ignore and continue */
    }
  }

  const fallback = isWindows ? 'python' : 'python3';
  return { command: fallback, source: 'PATH', display: `${fallback} (from PATH)` };
}

/** File name of the PyInstaller-built backend shipped inside `resources/zyra`. */
function packagedBackendCandidates(dir: string): string[] {
  return process.platform === 'win32'
    ? [path.join(dir, 'ZYRA-backend.exe'), path.join(dir, 'ZYRA-backend')]
    : [path.join(dir, 'ZYRA-backend'), path.join(dir, 'ZYRA-backend.exe')];
}

/** True when this directory holds the bundled backend executable. */
export function isPackagedBackendDir(dir: string): boolean {
  return packagedBackendCandidates(dir).some((file) => {
    try {
      return fs.existsSync(file);
    } catch {
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
export function resolveBackendLaunch(startDir?: string): BackendLaunch {
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
        const exe = packagedBackendCandidates(dir).find((f) => fs.existsSync(f)) as string;
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

