interface CommandItem {
  id: string;
  label: string;
  category: string;
}

interface ZyraAPI {
  aiChat: (message: string) => Promise<string>;
  executeCommand: (command: string) => Promise<string>;
  toggleVoice: (enabled: boolean) => Promise<string>;
  getVoiceStatus: () => Promise<{ listening: boolean }>;
  remember: (key: string, value: string) => Promise<string>;
  recall: (key: string) => Promise<string | null>;
  getCommands: () => Promise<CommandItem[]>;
  speak: (text: string) => Promise<string>;
  analyzeLink: (data: string | { url: string }) => Promise<any>;
  showNotification: (title: string, body: string) => void;
  saveConversation: (data: any) => Promise<string>;
  loadConversation: () => Promise<any>;
  selectDirectory: () => Promise<string | null>;
  quitAndInstall: () => void;
  onNavigate: (callback: (view: string) => void) => void;
  onViewShow: (callback: () => void) => void;
  onUpdateAvailable: (callback: (info: any) => void) => void;
  onUpdateDownloaded: (callback: (info: any) => void) => void;
}

interface Window {
  zyraAPI: ZyraAPI;
}

declare module '*.css' {
  const content: { [className: string]: string };
  export default content;
}

declare module '*.scss' {
  const content: { [className: string]: string };
  export default content;
}

declare module '*.sass' {
  const content: { [className: string]: string };
  export default content;
}

declare module '*.less' {
  const content: { [className: string]: string };
  export default content;
}

declare module '*.png' {
  const src: string;
  export default src;
}

declare module '*.jpg' {
  const src: string;
  export default src;
}

declare module '*.jpeg' {
  const src: string;
  export default src;
}

declare module '*.gif' {
  const src: string;
  export default src;
}

declare module '*.svg' {
  const src: string;
  export default src;
}
