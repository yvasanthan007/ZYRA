import { app, BrowserWindow, ipcMain } from 'electron';
import * as http from 'http';
import * as path from 'path';

type BackendMethod = 'GET' | 'POST';

interface BackendResponse {
  success: boolean;
  body?: unknown;
  error?: string;
  statusCode?: number;
}

const BACKEND_HOST = '127.0.0.1';
const BACKEND_PORT = 8080;
const REQUEST_TIMEOUT_MS = 15000;

const APPROVED_PATHS = new Set<string>([
  '/api/cyberllm/status',
  '/api/cyberllm/phishing',
  '/api/cyberllm/chat',
  '/api/health',
  '/api/ai/status',
  '/api/chat',
  '/api/command',
  '/api/voice',
  '/api/speak',
  '/api/speak/stop',
  '/api/analyze-link',
  '/api/system-metrics',
  '/api/ml/phishing',
  '/api/ml/phishing/model',
  '/api/ml/phishing/dataset',
  '/api/ml/phishing/capture',
  '/api/dns/lookup',
  '/api/dns/result',
  '/api/dns/report',
  '/api/dns/history',
]);

let mainWindow: BrowserWindow | null = null;

function forwardToBackend(
  method: BackendMethod,
  apiPath: string,
  payload?: unknown,
): Promise<BackendResponse> {
  return new Promise((resolve) => {
    if (!APPROVED_PATHS.has(apiPath)) {
      resolve({
        success: false,
        error: 'API path is not approved.',
      });
      return;
    }

    const body =
      method === 'POST' && payload !== undefined
        ? JSON.stringify(payload)
        : undefined;

    const req = http.request(
      {
        hostname: BACKEND_HOST,
        port: BACKEND_PORT,
        path: apiPath,
        method,
        headers: {
          Accept: 'application/json',
          ...(body
            ? {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(body),
              }
            : {}),
        },
      },
      (res) => {
        let responseText = '';

        res.setEncoding('utf8');

        res.on('data', (chunk: string) => {
          responseText += chunk;
        });

        res.on('end', () => {
          const statusCode = res.statusCode ?? 500;

          let responseBody: unknown = responseText;

          try {
            responseBody = responseText
              ? JSON.parse(responseText)
              : {};
          } catch {
            // Preserve a non-JSON response as text.
          }

          resolve({
            success: statusCode >= 200 && statusCode < 300,
            statusCode,
            body: responseBody,
            ...(statusCode >= 400
              ? { error: `Backend returned HTTP ${statusCode}` }
              : {}),
          });
        });
      },
    );

    req.setTimeout(REQUEST_TIMEOUT_MS, () => {
      req.destroy(new Error('Backend request timed out.'));
    });

    req.on('error', (error: Error) => {
      resolve({
        success: false,
        error: error.message,
      });
    });

    if (body) {
      req.write(body);
    }

    req.end();
  });
}

function registerBackendRequestHandler(): void {
  ipcMain.removeHandler('backend:request');

  ipcMain.handle(
    'backend:request',
    async (
      _event,
      method: string,
      apiPath: string,
      payload?: unknown,
    ): Promise<BackendResponse> => {
      if (method !== 'GET' && method !== 'POST') {
        return {
          success: false,
          error: 'Only GET and POST methods are permitted.',
        };
      }

      if (typeof apiPath !== 'string' || !APPROVED_PATHS.has(apiPath)) {
        return {
          success: false,
          error: 'API path is not approved.',
        };
      }

      return forwardToBackend(method, apiPath, payload);
    },
  );
}

function createWindow(): void {
  // Adjust these paths if webpack.config.js emits different filenames.
  const preloadPath = path.join(__dirname, '../preload/preload.js');
  const rendererPath = path.join(__dirname, '../renderer/index.html');

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 850,
    minWidth: 900,
    minHeight: 600,
    show: true,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  if (app.isPackaged) {
    void mainWindow.loadFile(rendererPath);
  } else {
    void mainWindow.loadFile(rendererPath);
  }
}

app.whenReady().then(() => {
  registerBackendRequestHandler();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});