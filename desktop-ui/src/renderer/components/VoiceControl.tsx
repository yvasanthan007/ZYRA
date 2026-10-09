import React, { useRef, useState } from 'react';

interface VoiceControlProps {
  setStatus: (status: string) => void;
}

interface VoicePayload {
  transcript?: string;
  response?: string;
  listening?: boolean;
}

const isVoicePayload = (value: unknown): value is VoicePayload => {
  if (typeof value !== 'object' || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.transcript === 'string' ||
    typeof record.response === 'string' ||
    typeof record.listening === 'boolean'
  );
};

const VoiceControl: React.FC<VoiceControlProps> = ({ setStatus }) => {
  const [isListening, setIsListening] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [response, setResponse] = useState('');
  const [error, setError] = useState('');
  // Guards against double-clicks / overlapping microphone requests. The
  // legacy bridge capture is synchronous and blocking, so a second click
  // while one capture is in flight must be ignored rather than queued.
  const requestInFlight = useRef(false);

  const toggleListening = async () => {
    if (requestInFlight.current) return;
    const newState = !isListening;
    // Stop never starts a capture: clear the listening affordance
    // immediately and tell the backend to stand down.
    if (!newState) {
      requestInFlight.current = true;
      setIsBusy(true);
      setIsListening(false);
      setStatus('Voice disabled');
      try {
        await window.zyraAPI.toggleVoice(false);
      } catch {
        // Best-effort: the capture (if any) already finished or failed.
      } finally {
        requestInFlight.current = false;
        setIsBusy(false);
      }
      return;
    }

    requestInFlight.current = true;
    setIsBusy(true);
    setError('');
    // Idle -> Listening: show the affordance before the blocking call.
    setIsListening(true);
    setStatus('Listening... speak clearly into your microphone');

    try {
      // Listening -> Recognizing -> Processing happens inside the bridge
      // (microphone capture + STT + backend routing). This promise resolves
      // with { transcript, response } or rejects with the failure reason.
      const raw = await window.zyraAPI.toggleVoice(true);
      const payload: VoicePayload = isVoicePayload(raw) ? raw : {};
      const heard = (payload.transcript || '').trim();
      const reply = (payload.response || '').trim();

      if (!heard) {
        // Response displayed (honest empty-transcript path) -> Idle.
        setTranscript('');
        setResponse(reply || "I didn't catch that. Please speak louder or try again.");
        setError('');
        setStatus('No speech recognized');
      } else {
        // Response displayed -> Idle.
        setTranscript(heard);
        setResponse(reply || '(Zyra has nothing to say for this command.)');
        setError('');
        setStatus('Ready');
      }
    } catch (err) {
      // Failure paths return to a usable state with an honest message.
      // Never display a successful recognition when no transcript arrived.
      const message = err instanceof Error ? err.message : 'Voice control error';
      setTranscript('');
      setResponse('');
      if (/STT unavailable|speech service|network/i.test(message)) {
        setError(`Speech recognition unavailable: ${message}`);
        setStatus('Voice recognition unavailable');
      } else if (/permission|denied|no .*microphone|not found|Voice capture error/i.test(message)) {
        setError(`Microphone error: ${message}`);
        setStatus('Microphone error');
      } else if (/didn't catch|no speech/i.test(message)) {
        setError(message);
        setStatus('No speech recognized');
      } else {
        setError(message);
        setStatus('Voice control error');
      }
    } finally {
      // Never remain stuck in Listening after resolve/reject/timeout.
      setIsListening(false);
      setIsBusy(false);
      requestInFlight.current = false;
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
          disabled={isBusy}
        >
          {isBusy ? 'Working...' : isListening ? 'Stop Listening' : 'Start Listening'}
        </button>
        {isListening && (
          <p className="voice-hint">Speak clearly into your microphone</p>
        )}
        {error && (
          <p className="voice-hint" role="alert">{error}</p>
        )}
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
