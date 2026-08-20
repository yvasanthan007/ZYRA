import { spawn, ChildProcess } from 'child_process';
import * as path from 'path';
import { app } from 'electron';

interface Command {
  type: string;
  data: unknown;
}

interface CommandResponse {
  success: boolean;
  data: unknown;
  error?: string;
}

export class PythonBridge {
  private process: ChildProcess | null = null;
  private requestId = 0;
  private pendingRequests: Map<number, { resolve: (value: unknown) => void; reject: (reason: unknown) => void }> = new Map();
  private buffer = '';

  /**
   * In development: use system Python and the source bridge_server.py
   * In production: use the bundled Python binary from process.resourcesPath
   *   (the binary can be either a PyInstaller one-file exe or a standalone
   *    interpreter + script pair placed in the resources directory)
   */
  private getPythonCommand(): string {
    if (app.isPackaged) {
      // Bundled via PyInstaller — check for the compiled binary first
      const bundledExe = path.join(process.resourcesPath, 'zyra_backend');
      const fs = require('fs');
      if (fs.existsSync(bundledExe)) return bundledExe;
      // Fall back to bundled Python interpreter
      const pythonPath = path.join(process.resourcesPath, 'python', 'python.exe');
      if (fs.existsSync(pythonPath)) return pythonPath;
      // Fall back to system Python (requires user to have Python installed)
      return 'python';
    }
    // Development mode
    return 'python';
  }

  private getBridgeScriptPath(): string {
    if (app.isPackaged) {
      // In packaged app, bridge_server.py is in resources
      return path.join(process.resourcesPath, 'bridge_server.py');
    }
    // In development: __dirname is dist/main/, script is at desktop-ui/bridge_server.py
    return path.join(__dirname, '../../bridge_server.py');
  }

  /**
   * In development: spawn `python <script>` (uses system Python + source files)
   * In production: spawn the bundled binary directly (no script path needed)
   */
  start(): void {
    const pythonCmd = this.getPythonCommand();

    if (app.isPackaged) {
      // Bundled binary — run directly (PyInstaller --onefile)
      const binaryPath = path.join(process.resourcesPath, 'zyra_backend');
      const fs = require('fs');
      if (fs.existsSync(binaryPath)) {
        this.spawnProcess(binaryPath, []);
      } else {
        // Fall back to interpreter + script
        this.spawnProcess(pythonCmd, [this.getBridgeScriptPath()]);
      }
    } else {
      // Development: spawn system Python with the script
      this.spawnProcess(pythonCmd, [this.getBridgeScriptPath()]);
    }
  }

  private spawnProcess(cmd: string, args: string[]): void {
    const cwd = app.isPackaged
      ? process.resourcesPath
      : path.join(__dirname, '../..');

    this.process = spawn(cmd, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      cwd,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',  // Ensure stdout is flushed immediately
      },
    });

    this.process.stdout?.on('data', (data: Buffer) => {
      this.buffer += data.toString();
      this.processBuffer();
    });

    this.process.stderr?.on('data', (data: Buffer) => {
      console.error('Python Bridge Error:', data.toString());
    });

    this.process.on('exit', (code: number | null) => {
      console.log('Python process exited with code:', code);
      this.process = null;
      // Reject all pending requests
      for (const [, pending] of this.pendingRequests) {
        pending.reject(new Error('Python process exited'));
      }
      this.pendingRequests.clear();
    });

    this.process.on('error', (err: Error) => {
      console.error('Failed to start Python process:', err);
    });
  }

  stop(): void {
    if (this.process) {
      this.process.kill();
      this.process = null;
    }
  }

  async sendCommand(command: Command, timeoutMs = 30000): Promise<unknown> {
    return new Promise((resolve, reject) => {
      if (!this.process || !this.process.stdin) {
        reject(new Error('Python process not running'));
        return;
      }

      const id = ++this.requestId;

      // Set timeout to prevent hanging
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(id);
        reject(new Error(`Command timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      this.pendingRequests.set(id, {
        resolve: (value: unknown) => {
          clearTimeout(timeout);
          resolve(value);
        },
        reject: (reason: unknown) => {
          clearTimeout(timeout);
          reject(reason);
        },
      });

      const message = JSON.stringify({ id, ...command }) + '\n';
      this.process.stdin.write(message, (err) => {
        if (err) {
          clearTimeout(timeout);
          this.pendingRequests.delete(id);
          reject(err);
        }
      });
    });
  }

  private processBuffer(): void {
    const lines = this.buffer.split('\n');
    // Keep the last incomplete line in the buffer
    this.buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.trim()) continue;

      try {
        const response: { id: number; success: boolean; data: unknown; error?: string } = JSON.parse(line);
        const pending = this.pendingRequests.get(response.id);
        if (pending) {
          this.pendingRequests.delete(response.id);
          if (response.success) {
            pending.resolve(response.data);
          } else {
            pending.reject(new Error(response.error || 'Unknown error'));
          }
        }
      } catch (e) {
        console.error('Failed to parse Python response:', line);
      }
    }
  }

  isRunning(): boolean {
    return this.process !== null && !this.process.killed;
  }
}
