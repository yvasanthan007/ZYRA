import React, { useState, useEffect } from 'react';

interface VoiceControlProps {
  setStatus: (status: string) => void;
}

const VoiceControl: React.FC<VoiceControlProps> = ({ setStatus }) => {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [response, setResponse] = useState('');

  const toggleListening = async () => {
    const newState = !isListening;
    setIsListening(newState);
    setStatus(newState ? 'Listening...' : 'Voice disabled');

    try {
      await window.zyraAPI.toggleVoice(newState);
      if (newState) {
        // Start polling for voice status in real use case
        setTranscript('');
        setResponse('');
      }
    } catch (err) {
      setStatus('Voice control error');
      setIsListening(false);
    }
  };

  const handleTranscriptInput = async (text: string) => {
    if (!text.trim()) return;
    setTranscript(text);
    setStatus('Processing...');
    try {
      const result = await window.zyraAPI.executeCommand(text);
      setResponse(typeof result === 'string' ? result : 'Command executed');
      setStatus('Voice disabled');
      setIsListening(false);
    } catch (err) {
      setResponse('Error processing voice command');
      setStatus('Error');
    }
  };

  return (
    <div className="voice-control">
      <div className="voice-status-card">
        <div className={`voice-indicator ${isListening ? 'active' : 'inactive'}`}>
          <span className="mic-icon">{isListening ? '🎙️' : '🎤'}</span>
          <h2>{isListening ? 'Listening' : 'Voice Off'}</h2>
        </div>
        <button
          className={`voice-toggle-button ${isListening ? 'active' : ''}`}
          onClick={toggleListening}
        >
          {isListening ? 'Stop Listening' : 'Start Listening'}
        </button>
        {isListening && (
          <p className="voice-hint">Speak clearly into your microphone</p>
        )}
      </div>

      <div className="voice-manual-input">
        <h3>Manual Voice Input</h3>
        <div className="voice-input-group">
          <input
            type="text"
            className="voice-text-input"
            placeholder="Type what you would say (e.g., 'open chrome')..."
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handleTranscriptInput(transcript);
              }
            }}
          />
          <button
            className="voice-send-button"
            onClick={() => handleTranscriptInput(transcript)}
            disabled={!transcript.trim()}
          >
            Send
          </button>
        </div>
      </div>

      {(transcript || response) && (
        <div className="voice-transcript-area">
          {transcript && (
            <div className="transcript-item">
              <span className="transcript-label">You said:</span>
              <p>{transcript}</p>
            </div>
          )}
          {response && (
            <div className="transcript-item">
              <span className="transcript-label">ZYRA:</span>
              <p>{response}</p>
            </div>
          )}
        </div>
      )}

      <div className="voice-info">
        <h3>Voice Commands</h3>
        <ul>
          <li>"Open Chrome" - Launch Google Chrome</li>
          <li>"Open VS Code" - Launch Visual Studio Code</li>
          <li>"What is the time?" - Get current time</li>
          <li>"Search Google for [query]" - Search the web</li>
          <li>"Shutdown" - Shutdown the PC</li>
          <li>"Volume up" / "Volume down" - Adjust volume</li>
          <li>"Screenshot" - Take a screenshot</li>
          <li>"Lock" - Lock the PC</li>
          <li>"Exit" - Close ZYRA</li>
        </ul>
      </div>
    </div>
  );
};

export default VoiceControl;
