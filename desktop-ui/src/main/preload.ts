import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('zyraAPI', {
  // AI Chat
  aiChat: (message: string): Promise<string> =>
    ipcRenderer.invoke('ai:chat', message),

  // System Commands
  executeCommand: (command: string): Promise<string> =>
    ipcRenderer.invoke('command:execute', command),

  // Voice Control
  toggleVoice: (enabled: boolean): Promise<string> =>
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
});
