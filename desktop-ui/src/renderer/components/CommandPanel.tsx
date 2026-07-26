import React, { useState, useEffect } from 'react';

interface CommandItem {
  id: string;
  label: string;
  category: string;
}

interface CommandPanelProps {
  setStatus: (status: string) => void;
}

const categoryLabels: Record<string, string> = {
  apps: 'Applications',
  web: 'Web & Search',
  system: 'System Controls',
  info: 'Information',
  media: 'Media',
};

const CommandPanel: React.FC<CommandPanelProps> = ({ setStatus }) => {
  const [commands, setCommands] = useState<CommandItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [executingId, setExecutingId] = useState<string | null>(null);

  useEffect(() => {
    loadCommands();
  }, []);

  const loadCommands = async () => {
    try {
      const cmds = await window.zyraAPI.getCommands();
      setCommands(cmds);
    } catch (err) {
      setStatus('Failed to load commands');
    } finally {
      setLoading(false);
    }
  };

  const handleExecute = async (cmd: CommandItem) => {
    setExecutingId(cmd.id);
    setStatus(`Executing: ${cmd.label}...`);
    try {
      const result = await window.zyraAPI.executeCommand(cmd.id);
      setStatus(result || `Executed: ${cmd.label}`);
    } catch (err) {
      setStatus(`Failed: ${cmd.label}`);
    } finally {
      setExecutingId(null);
    }
  };

  const groupedCommands = commands.reduce<Record<string, CommandItem[]>>((acc, cmd) => {
    if (!acc[cmd.category]) acc[cmd.category] = [];
    acc[cmd.category].push(cmd);
    return acc;
  }, {});

  if (loading) {
    return <div className="loading-state">Loading commands...</div>;
  }

  return (
    <div className="command-panel">
      {Object.entries(groupedCommands).map(([category, cmds]) => (
        <div key={category} className="command-category">
          <h3 className="category-title">
            {categoryLabels[category] || category}
          </h3>
          <div className="command-grid">
            {cmds.map((cmd) => (
              <button
                key={cmd.id}
                className={`command-button ${executingId === cmd.id ? 'executing' : ''}`}
                onClick={() => handleExecute(cmd)}
                disabled={executingId !== null}
                title={cmd.label}
              >
                <span className="command-label">{cmd.label}</span>
                {executingId === cmd.id && <span className="spinner" />}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

export default CommandPanel;
