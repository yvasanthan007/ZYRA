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
  getSystemMetrics: () => Promise<any>;
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
