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

  // Text-to-Speech
  speak: (text: string): Promise<string> =>
    ipcRenderer.invoke('app:speak', text),

  // Link Security Analysis
  analyzeLink: (data: string | { url: string }): Promise<any> =>
    ipcRenderer.invoke('security:analyze-link', data),

  // Notifications
  showNotification: (title: string, body: string): void =>
    ipcRenderer.invoke('app:notification', title, body),

  // File System
  saveConversation: (data: any): Promise<string> =>
    ipcRenderer.invoke('fs:save-conversation', data),

  loadConversation: (): Promise<any> =>
    ipcRenderer.invoke('fs:load-conversation'),

  selectDirectory: (): Promise<string | null> =>
    ipcRenderer.invoke('fs:select-directory'),

  // Updates
  quitAndInstall: (): void =>
    ipcRenderer.invoke('app:quit-and-install'),

  // Navigation (send messages from main to renderer)
  onNavigate: (callback: (view: string) => void) => {
    ipcRenderer.on('navigate:chat', () => callback('chat'));
  },
  onViewShow: (callback: () => void) => {
    ipcRenderer.on('window:show', () => callback());
  },
  onUpdateAvailable: (callback: (info: any) => void) => {
    ipcRenderer.on('app:update-available', (_event, info) => callback(info));
  },
  onUpdateDownloaded: (callback: (info: any) => void) => {
    ipcRenderer.on('app:update-downloaded', (_event, info) => callback(info));
  },
});
