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
}

interface Window {
  zyraAPI: ZyraAPI;
}
