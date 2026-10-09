import { contextBridge, ipcRenderer } from 'electron';
import type { BackendStatus } from './backend-service';

contextBridge.exposeInMainWorld('zyraAPI', {
  // AI Chat
  aiChat: (message: string): Promise<string> =>
    ipcRenderer.invoke('ai:chat', message),

  // System Commands
  executeCommand: (command: string): Promise<string> =>
    ipcRenderer.invoke('command:execute', command),

  // Voice Control — returns the recognized transcript + assistant reply.
  // Contract: resolves { transcript: string; response: string } on success
  // (empty transcript + helper reply when nothing was heard); rejects with
  // an Error carrying the failure reason (STT unavailable / mic / backend).
  toggleVoice: (enabled: boolean): Promise<{ transcript: string; response: string }> =>
    ipcRenderer.invoke('voice:toggle', enabled),

  getVoiceStatus: (): Promise<{ listening: boolean }> =>
    ipcRenderer.invoke('voice:status'),

  // Memory
  remember: (key: string, value: string): Promise<string> =>
    ipcRenderer.invoke('memory:remember', key, value),

  recall: (key: string): Promise<string | null> =>
    ipcRenderer.invoke('memory:recall', key),

  // Commands List
  getCommands: (): Promise<Array<{ id: string; label: string; category: string }>> =>
    ipcRenderer.invoke('commands:list'),

  // System Monitor Metrics
  getSystemMetrics: (): Promise<any> =>
    ipcRenderer.invoke('system:metrics'),

  // ── FastAPI backend lifecycle (started automatically by Electron) ──
  getBackendStatus: (): Promise<BackendStatus | null> =>
    ipcRenderer.invoke('backend:status'),

  onBackendStatus: (callback: (status: BackendStatus | null) => void): (() => void) => {
    const listener = (_event: unknown, status: BackendStatus | null) => callback(status);
    ipcRenderer.on('backend:status', listener);
    return () => ipcRenderer.removeListener('backend:status', listener);
  },

  getBackendLogs: (): Promise<string[]> =>
    ipcRenderer.invoke('backend:logs'),

  restartBackend: (): Promise<BackendStatus | null> =>
    ipcRenderer.invoke('backend:restart'),

  requestBackend: (method: string, apiPath: string, payload?: unknown): Promise<unknown> =>
    ipcRenderer.invoke('backend:request', method, apiPath, payload),

  // Open the existing React desktop UI in its own window.
  openDesktopUi: (): Promise<boolean> =>
    ipcRenderer.invoke('ui:open-desktop'),
});
