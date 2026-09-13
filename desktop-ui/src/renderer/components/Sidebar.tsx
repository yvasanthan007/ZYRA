import React from 'react';

type View = 'chat' | 'commands' | 'monitor' | 'voice';

interface SidebarProps {
  activeView: View;
  onViewChange: (view: View) => void;
  onSettingsClick: () => void;
}

const navItems: Array<{ id: View; label: string; icon: string }> = [
  { id: 'chat', label: 'Chat', icon: '💬' },
  { id: 'commands', label: 'Commands', icon: '⚡' },
  { id: 'monitor', label: 'Monitor', icon: '📊' },
  { id: 'voice', label: 'Voice', icon: '🎤' },
];

const Sidebar: React.FC<SidebarProps> = ({ activeView, onViewChange, onSettingsClick }) => {
  return (
    <nav className="sidebar">
      <div className="sidebar-logo">
        <span className="logo-icon">🤖</span>
        <span className="logo-text">ZYRA</span>
      </div>
      <ul className="sidebar-nav">
        {navItems.map((item) => (
          <li key={item.id}>
            <button
              className={`nav-button ${activeView === item.id ? 'active' : ''}`}
              onClick={() => onViewChange(item.id)}
              title={item.label}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="sidebar-bottom">
        <button
          className="nav-button settings-button"
          onClick={onSettingsClick}
          title="Settings"
        >
          <span className="nav-icon">⚙️</span>
          <span className="nav-label">Settings</span>
        </button>
      </div>
    </nav>
  );
};

export default Sidebar;

