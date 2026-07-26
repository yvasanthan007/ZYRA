import { spawn, ChildProcess } from 'child_process';
import * as path from 'path';

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

  start(): void {
    // __dirname is dist/main/ ; bridge_server.py is at desktop-ui/bridge_server.py
    const scriptPath = path.join(__dirname, '../../bridge_server.py');
    
    this.process = spawn('python', [scriptPath], {
      stdio: ['pipe', 'pipe', 'pipe'],
      cwd: path.join(__dirname, '../..'),
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

  async sendCommand(command: Command): Promise<unknown> {
    return new Promise((resolve, reject) => {
      if (!this.process || !this.process.stdin) {
        reject(new Error('Python process not running'));
        return;
      }

      const id = ++this.requestId;
      this.pendingRequests.set(id, { resolve, reject });

      const message = JSON.stringify({ id, ...command }) + '\n';
      this.process.stdin.write(message);
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
