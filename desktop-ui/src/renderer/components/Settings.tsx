import React, { useState } from 'react';

interface SettingsProps {
  setStatus: (status: string) => void;
}

const Settings: React.FC<SettingsProps> = ({ setStatus }) => {
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [modelName, setModelName] = useState('llama3');
  const [recallKey, setRecallKey] = useState('');
  const [recallValue, setRecallValue] = useState('');
  const [rememberedKey, setRememberedKey] = useState('');
  const [rememberedValue, setRememberedValue] = useState('');

  const handleSave = () => {
    setStatus('Settings saved');
  };

  const handleRemember = async () => {
    if (!rememberedKey.trim() || !rememberedValue.trim()) return;
    try {
      await window.zyraAPI.remember(rememberedKey.trim(), rememberedValue.trim());
      setStatus(`Remembered: ${rememberedKey}`);
      setRememberedKey('');
      setRememberedValue('');
    } catch (err) {
      setStatus('Failed to save memory');
    }
  };

  const handleRecall = async () => {
    if (!recallKey.trim()) return;
    try {
      const value = await window.zyraAPI.recall(recallKey.trim());
      setRecallValue(value || 'Not found');
    } catch (err) {
      setRecallValue('Error recalling');
    }
  };

  return (
    <div className="settings-view">
      <div className="settings-section">
        <h3>AI Model</h3>
        <div className="setting-row">
          <label>Model Name</label>
          <select
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
          >
            <option value="llama3">Llama 3</option>
            <option value="llama2">Llama 2</option>
            <option value="mistral">Mistral</option>
            <option value="codellama">Code Llama</option>
          </select>
        </div>
      </div>

      <div className="settings-section">
        <h3>Voice Settings</h3>
        <div className="setting-row">
          <label>Enable Voice</label>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={voiceEnabled}
              onChange={(e) => setVoiceEnabled(e.target.checked)}
            />
            <span className="toggle-slider"></span>
          </label>
        </div>
      </div>

      <div className="settings-section">
        <h3>Memory</h3>
        <div className="setting-row">
          <label>Remember</label>
          <div className="memory-input-group">
            <input
              type="text"
              placeholder="Key"
              value={rememberedKey}
              onChange={(e) => setRememberedKey(e.target.value)}
            />
            <input
              type="text"
              placeholder="Value"
              value={rememberedValue}
              onChange={(e) => setRememberedValue(e.target.value)}
            />
            <button onClick={handleRemember}>Save</button>
          </div>
        </div>
        <div className="setting-row">
          <label>Recall</label>
          <div className="memory-input-group">
            <input
              type="text"
              placeholder="Key"
              value={recallKey}
              onChange={(e) => setRecallKey(e.target.value)}
            />
            <button onClick={handleRecall}>Get</button>
          </div>
          {recallValue && (
            <p className="recall-result">Result: {recallValue}</p>
          )}
        </div>
      </div>

      <div className="settings-section">
        <h3>About</h3>
        <div className="about-info">
          <p><strong>ZYRA</strong> - AI Desktop Assistant</p>
          <p>Version: 1.0.0</p>
          <p>Built with Electron + React + TypeScript</p>
        </div>
      </div>

      <button className="save-settings-button" onClick={handleSave}>
        Save Settings
      </button>
    </div>
  );
};

export default Settings;
