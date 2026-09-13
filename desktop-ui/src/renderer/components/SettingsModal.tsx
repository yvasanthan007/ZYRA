import React from 'react';
import Settings from './Settings';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  setStatus: (status: string) => void;
}

const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose, setStatus }) => {
  if (!isOpen) return null;

  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div className="settings-modal-overlay" onClick={handleOverlayClick}>
      <div className="settings-modal-panel">
        <button className="settings-modal-close" onClick={onClose} title="Close Settings">
          ✕
        </button>
        <Settings setStatus={setStatus} onClose={onClose} />
      </div>
    </div>
  );
};

export default SettingsModal;
