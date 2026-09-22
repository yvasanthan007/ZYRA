import React from 'react';

type View = 'chat' | 'commands' | 'monitor' | 'settings';

interface SidebarProps {
  activeView: View;
  onViewChange: (view: View) => void;
}

const navItems: Array<{ id: View; label: string; icon: string }> = [
  { id: 'chat', label: 'Chat', icon: '💬' },
  { id: 'commands', label: 'Commands', icon: '⚡' },
  { id: 'monitor', label: 'Monitor', icon: '📊' },
  { id: 'settings', label: 'Settings', icon: '⚙️' },
];

const Sidebar: React.FC<SidebarProps> = ({ activeView, onViewChange }) => {
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
    </nav>
  );
};

export default Sidebar;
