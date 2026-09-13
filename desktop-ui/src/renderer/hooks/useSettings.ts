import { useState, useEffect, useCallback } from 'react';

export interface ZyraSettings {
  theme: 'dark' | 'light';
  fontSize: number;
  voiceEnabled: boolean;
  voiceVolume: number;
  wakeWord: string;
  saveChatHistory: boolean;
  chatSidebarOpen: boolean;
}

const DEFAULT_SETTINGS: ZyraSettings = {
  theme: 'dark',
  fontSize: 14,
  voiceEnabled: true,
  voiceVolume: 70,
  wakeWord: 'Hey ZYRA',
  saveChatHistory: true,
  chatSidebarOpen: false,
};

const STORAGE_KEY = 'zyra_settings';

function loadSettings(): ZyraSettings {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return { ...DEFAULT_SETTINGS, ...parsed };
    }
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
  return DEFAULT_SETTINGS;
}

function saveSettings(settings: ZyraSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch (e) {
    console.error('Failed to save settings:', e);
  }
}

export function useSettings() {
  const [settings, setSettings] = useState<ZyraSettings>(loadSettings);

  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  useEffect(() => {
    // Apply theme
    document.documentElement.setAttribute('data-theme', settings.theme);
    
    // Apply font size
    document.documentElement.style.setProperty('--font-size-base', `${settings.fontSize}px`);
  }, [settings.theme, settings.fontSize]);

  const updateSetting = useCallback(<K extends keyof ZyraSettings>(
    key: K,
    value: ZyraSettings[K]
  ) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  }, []);

  const resetSettings = useCallback(() => {
    setSettings(DEFAULT_SETTINGS);
  }, []);

  return {
    settings,
    updateSetting,
    resetSettings,
  };
}
