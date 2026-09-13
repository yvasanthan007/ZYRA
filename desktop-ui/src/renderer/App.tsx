import React, { useState } from 'react';
import { SettingsProvider } from './context/SettingsContext';
import Sidebar from './components/Sidebar';
import ChatView from './components/ChatView';
import CommandPanel from './components/CommandPanel';
import VoiceControl from './components/VoiceControl';
import SettingsModal from './components/SettingsModal';
import SystemMonitor from './components/SystemMonitor';

type View = 'chat' | 'commands' | 'monitor' | 'voice';

const AppContent: React.FC = () => {
  const [activeView, setActiveView] = useState<View>('chat');
  const [statusMessage, setStatusMessage] = useState('Ready');
  const [settingsOpen, setSettingsOpen] = useState(false);

  const renderView = () => {
    switch (activeView) {
      case 'chat':
        return <ChatView setStatus={setStatusMessage} />;
      case 'commands':
        return <CommandPanel setStatus={setStatusMessage} />;
      case 'monitor':
        return <SystemMonitor setStatus={setStatusMessage} />;
      case 'voice':
        return <VoiceControl setStatus={setStatusMessage} />;
      default:
        return <ChatView setStatus={setStatusMessage} />;
    }
  };

  return (
    <div className="app-container">
      <Sidebar
        activeView={activeView}
        onViewChange={setActiveView}
        onSettingsClick={() => setSettingsOpen(true)}
      />
      <main className="main-content">
        <header className="app-header">
          <h1>ZYRA</h1>
        </header>
        <div className="view-container">
          {renderView()}
        </div>
      </main>
      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        setStatus={setStatusMessage}
      />
    </div>
  );
};

const App: React.FC = () => {
  return (
    <SettingsProvider>
      <AppContent />
    </SettingsProvider>
  );
};

export default App;

