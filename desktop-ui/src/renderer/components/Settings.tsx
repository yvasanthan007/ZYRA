import React, { useState } from 'react';
import { useSettingsContext } from '../context/SettingsContext';
import ConfirmationDialog from './ConfirmationDialog';

interface SettingsProps {
  setStatus: (status: string) => void;
  onClose?: () => void;
}

const CHAT_HISTORY_KEY = 'zyra_chat_history';

const Settings: React.FC<SettingsProps> = ({ setStatus, onClose }) => {
  const { settings, updateSetting } = useSettingsContext();
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
  }>({ isOpen: false, title: '', message: '', onConfirm: () => {} });

  const handleClearChatHistory = () => {
    setConfirmDialog({
      isOpen: true,
      title: 'Clear Chat History',
      message: 'Are you sure you want to clear all chat history? This action cannot be undone.',
      onConfirm: () => {
        localStorage.removeItem(CHAT_HISTORY_KEY);
        setStatus('Chat history cleared');
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
      },
    });
  };

  const handleClearStoredData = () => {
    setConfirmDialog({
      isOpen: true,
      title: 'Clear All Stored Data',
      message: 'This will remove all saved memories, settings, and chat history. Are you sure?',
      onConfirm: () => {
        const keysToRemove = Object.keys(localStorage).filter(
          (key) => key.startsWith('zyra_')
        );
        keysToRemove.forEach((key) => localStorage.removeItem(key));
        setStatus('All stored data cleared');
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
      },
    });
  };

  return (
    <div className="settings-panel">
      <div className="settings-header">
        <h2 className="settings-title">⚙️ ZYRA SETTINGS</h2>
        <p className="settings-subtitle">// Neural core configuration</p>
      </div>
      {/* Section 1: THEME */}
      <div className="settings-section">
        <h3 className="section-title">
          <span className="section-icon">🎨</span> THEME
        </h3>
        <div className="setting-row">
          <label>Interface Theme</label>
          <div className="theme-toggle-group">
            <button
              className={`theme-toggle ${settings.theme === 'dark' ? 'active' : ''}`}
              onClick={() => {
                updateSetting('theme', 'dark');
                setStatus('Dark theme activated');
              }}
            >
              <span className="theme-preview dark-preview"></span>
              <span>Dark</span>
              <small>Black & Orange</small>
            </button>
            <button
              className={`theme-toggle ${settings.theme === 'light' ? 'active' : ''}`}
              onClick={() => {
                updateSetting('theme', 'light');
                setStatus('Light theme activated');
              }}
            >
              <span className="theme-preview light-preview"></span>
              <span>Light</span>
              <small>Blue & White</small>
            </button>
          </div>
        </div>
      </div>

      {/* Section 2: APPEARANCE */}
      <div className="settings-section">
        <h3 className="section-title">
          <span className="section-icon">✨</span> APPEARANCE
        </h3>
        <div className="setting-row">
          <label>Font Size</label>
          <div className="font-size-control">
            <input
              type="range"
              className="slider-input"
              min="12"
              max="20"
              value={settings.fontSize}
              onChange={(e) => updateSetting('fontSize', parseInt(e.target.value, 10))}
            />
            <span className="font-size-value">{settings.fontSize}px</span>
          </div>
        </div>
      </div>

      {/* Section 3: VOICE */}
      <div className="settings-section">
        <h3 className="section-title">
          <span className="section-icon">🎤</span> VOICE
        </h3>
        <div className="setting-row">
          <label>Voice Assistant</label>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={settings.voiceEnabled}
              onChange={(e) => {
                updateSetting('voiceEnabled', e.target.checked);
                setStatus(e.target.checked ? 'Voice assistant enabled' : 'Voice assistant disabled');
              }}
            />
            <span className="toggle-slider"></span>
          </label>
        </div>
        <div className="setting-row">
          <label>Voice Volume</label>
          <div className="volume-control">
            <input
              type="range"
              className="slider-input"
              min="0"
              max="100"
              value={settings.voiceVolume}
              onChange={(e) => updateSetting('voiceVolume', parseInt(e.target.value, 10))}
            />
            <span className="volume-value">{settings.voiceVolume}%</span>
          </div>
        </div>
      </div>

      {/* Section 4: AUTHENTICATION */}
      <div className="settings-section">
        <h3 className="section-title">
          <span className="section-icon">🔐</span> AUTHENTICATION
        </h3>
        <div className="setting-row">
          <label>Wake Word to Authenticate</label>
          <div className="wake-word-input">
            <input
              type="text"
              placeholder='e.g., "Hey ZYRA"'
              value={settings.wakeWord}
              onChange={(e) => updateSetting('wakeWord', e.target.value)}
            />
          </div>
        </div>
        <p className="setting-hint">
          Say this phrase to activate voice command mode. Example: "Hey ZYRA"
        </p>
      </div>

      {/* Section 5: CHAT */}
      <div className="settings-section">
        <h3 className="section-title">
          <span className="section-icon">💬</span> CHAT
        </h3>
        <div className="setting-row">
          <label>Save Chat History</label>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={settings.saveChatHistory}
              onChange={(e) => {
                updateSetting('saveChatHistory', e.target.checked);
                setStatus(e.target.checked ? 'Chat history saving enabled' : 'Chat history saving disabled');
              }}
            />
            <span className="toggle-slider"></span>
          </label>
        </div>
        <p className="setting-hint">
          Save conversations across sessions similar to ChatGPT
        </p>
        <div className="setting-row">
          <label>Chat Sidebar</label>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={settings.chatSidebarOpen}
              onChange={(e) => {
                updateSetting('chatSidebarOpen', e.target.checked);
                setStatus(e.target.checked ? 'Chat sidebar opened' : 'Chat sidebar closed');
              }}
            />
            <span className="toggle-slider"></span>
          </label>
        </div>
        <p className="setting-hint">
          Access your previous conversations through the sidebar
        </p>
      </div>

      {/* Section 6: DATA & PRIVACY */}
      <div className="settings-section">
        <h3 className="section-title">
          <span className="section-icon">🛡️</span> DATA & PRIVACY
        </h3>
        
        <div className="data-actions">
          <button className="data-action-button" onClick={() => setStatus('Manage Chat History - Feature coming soon')}>
            📋 Manage Chat History
          </button>
          <button className="data-action-button danger" onClick={handleClearChatHistory}>
            🗑️ Clear Chat History
          </button>
          <button className="data-action-button danger" onClick={handleClearStoredData}>
            🧹 Clear All Stored Data
          </button>
        </div>

        <div className="privacy-info">
          <h4>Privacy Information</h4>
          <ul>
            <li>
              <strong>Local Storage Only:</strong> ZYRA stores all data locally on your device.
              No data is sent to external servers.
            </li>
            <li>
              <strong>Chat History:</strong> Conversations are saved in your browser's local storage
              when enabled. You can clear them at any time.
            </li>
            <li>
              <strong>Memory:</strong> Key-value pairs you save via the memory feature are stored
              locally in a JSON file.
            </li>
            <li>
              <strong>No Tracking:</strong> ZYRA does not collect usage analytics or personal
              information.
            </li>
            <li>
              <strong>Full Control:</strong> You can clear all stored data at any time using the
              "Clear All Stored Data" button above.
            </li>
          </ul>
        </div>
      </div>

      {/* Confirmation Dialog */}
      <ConfirmationDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        confirmLabel="Yes, Clear"
        cancelLabel="Cancel"
        danger={true}
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog((prev) => ({ ...prev, isOpen: false }))}
      />
    </div>
  );
};

export default Settings;


