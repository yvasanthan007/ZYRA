import React, { createContext, useContext, ReactNode } from 'react';
import { useSettings, ZyraSettings } from '../hooks/useSettings';

interface SettingsContextType {
  settings: ZyraSettings;
  updateSetting: <K extends keyof ZyraSettings>(key: K, value: ZyraSettings[K]) => void;
  resetSettings: () => void;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

interface SettingsProviderProps {
  children: ReactNode;
}

export const SettingsProvider: React.FC<SettingsProviderProps> = ({ children }) => {
  const { settings, updateSetting, resetSettings } = useSettings();

  return (
    <SettingsContext.Provider value={{ settings, updateSetting, resetSettings }}>
      {children}
    </SettingsContext.Provider>
  );
};

export const useSettingsContext = (): SettingsContextType => {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error('useSettingsContext must be used within a SettingsProvider');
  }
  return context;
};
