import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import ChatView from './components/ChatView';
import CommandPanel from './components/CommandPanel';
import VoiceControl from './components/VoiceControl';
import Settings from './components/Settings';

type View = 'chat' | 'commands' | 'voice' | 'settings';

const App: React.FC = () => {
  const [activeView, setActiveView] = useState<View>('chat');
  const [statusMessage, setStatusMessage] = useState('Ready');

  const renderView = () => {
    switch (activeView) {
      case 'chat':
        return <ChatView setStatus={setStatusMessage} />;
      case 'commands':
        return <CommandPanel setStatus={setStatusMessage} />;
      case 'voice':
        return <VoiceControl setStatus={setStatusMessage} />;
      case 'settings':
        return <Settings setStatus={setStatusMessage} />;
      default:
        return <ChatView setStatus={setStatusMessage} />;
    }
  };

  return (
    <div className="app-container">
      <Sidebar activeView={activeView} onViewChange={setActiveView} />
      <main className="main-content">
        <header className="app-header">
          <h1>ZYRA</h1>
          <span className="status-badge">{statusMessage}</span>
        </header>
        <div className="view-container">
          {renderView()}
        </div>
      </main>
    </div>
  );
};

export default App;
