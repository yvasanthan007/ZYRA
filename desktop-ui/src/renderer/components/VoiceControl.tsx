import React, { useEffect, useRef, useState } from 'react';

interface VoiceControlProps {
  setStatus: (status: string) => void;
}

interface VoicePayload {
  transcript?: string;
  response?: string;
  listening?: boolean;
  error?: string;
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

// ZYRA speaks with the backend's Edge neural voice (en-US-JennyNeural first,
// then en-US-AriaNeural, en-US-AvaNeural, en-US-EmmaNeural as fallbacks),
// requested through POST /api/speak. Only when the backend is unreachable
// does the UI fall back to a local OS/Chromium speechSynthesis voice, and
// that substitution is reported in the status line. The OS/Chromium default
// is often a male voice (e.g. Microsoft David), so a female voice is picked
// explicitly whenever one is installed.
// Ordered name hints mirroring speak.py's DEFAULT_VOICE / FALLBACK_VOICES.
const PREFERRED_VOICE_HINTS = ['jenny', 'aria', 'ava', 'emma'];

const FEMALE_VOICE_HINTS = [
  'zira', 'aria', 'jenny', 'samantha', 'susan', 'hazel', 'maria', 'linda',
  'mary', 'salli', 'joanna', 'neerja', 'priya', 'female', 'eva', 'allison',
  'sara', 'karen', 'moira', 'tessa', 'fiona', 'veena', 'rishi',
];

const isEnUs = (voice: SpeechSynthesisVoice): boolean => {
  const tag = (voice.lang || '').replace('_', '-').toLowerCase();
  return tag === 'en-us' || tag === 'en';
};

const isFemaleName = (voice: SpeechSynthesisVoice): boolean => {
  const name = (voice.name || '').toLowerCase();
  return FEMALE_VOICE_HINTS.some((hint) => name.includes(hint));
};

// Prefer the backend's preferred voice names in order (Jenny, Aria, Ava,
// Emma); otherwise fall back to an installed en-US female voice; then any
// female voice; then an en-US voice. Returns null so callers can keep the
// browser default when no suitable voice is installed.
const pickFemaleVoice = (voices: SpeechSynthesisVoice[]):
  SpeechSynthesisVoice | null => {
  if (!voices.length) return null;
  for (const hint of PREFERRED_VOICE_HINTS) {
    const exact = voices.find((v) => isEnUs(v) && (v.name || '').toLowerCase().includes(hint));
    if (exact) return exact;
    const any = voices.find((v) => (v.name || '').toLowerCase().includes(hint));
    if (any) return any;
  }
  return (
    voices.find((v) => isEnUs(v) && isFemaleName(v)) ||
    voices.find((v) => isFemaleName(v)) ||
    voices.find((v) => isEnUs(v)) ||
    null
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

  // Speak responses with Zyra's configured Edge neural voice (en-US-JennyNeural)
  // by asking the backend TTS pipeline to speak (POST /api/speak). The browser's
  // speechSynthesis voices are local OS voices (e.g. Microsoft Zira/David) and
  // cannot be a cloud neural voice, so they are used only when the backend is
  // unreachable — and the substitution is reported in the status line, never
  // silent. The backend call returns immediately (speech runs in its own
  // thread), so the UI is never blocked.
  useEffect(() => {
    if (!response) return undefined;
    let stopped = false;

    // Chunked local playback (fallback only): Chromium stops long utterances
    // mid-answer, so resume in chunks without dropping any response text.
    const speakViaLocalVoice = () => {
      if (!('speechSynthesis' in window)) return;
      window.speechSynthesis.cancel();
      const speechLang = 'en-US';
      const chunks: string[] = [];
      for (let start = 0; start < response.length;) {
        let end = Math.min(start + 180, response.length);
        if (end < response.length) {
          const boundary = response.lastIndexOf(' ', end);
          if (boundary > start + 90) end = boundary + 1;
        }
        const chunk = response.slice(start, end).trim();
        if (chunk) chunks.push(chunk);
        start = end;
      }
      let chunkIndex = 0;
      const speakNextChunk = () => {
        if (stopped || chunkIndex >= chunks.length) return;
        const chunk = chunks[chunkIndex++];
        const nextUtterance = new SpeechSynthesisUtterance(chunk);
        nextUtterance.lang = speechLang;
        const female = pickFemaleVoice(window.speechSynthesis.getVoices());
        if (female) nextUtterance.voice = female;
        nextUtterance.onend = speakNextChunk;
        nextUtterance.onerror = speakNextChunk;
        window.speechSynthesis.speak(nextUtterance);
      };
      // Voices may still be loading when the response first arrives; wait for
      // them (once) so the female voice is selected rather than the default.
      const voices = window.speechSynthesis.getVoices();
      if (voices.length === 0) {
        let started = false;
        const startOnce = () => {
          if (started || stopped) return;
          started = true;
          window.clearTimeout(timer);
          speakNextChunk();
        };
        const onVoicesChanged = () => {
          window.speechSynthesis.removeEventListener('voiceschanged', onVoicesChanged);
          startOnce();
        };
        window.speechSynthesis.addEventListener('voiceschanged', onVoicesChanged);
        // Safety net: never leave the response silent if voices never load.
        const timer = window.setTimeout(() => {
          window.speechSynthesis.removeEventListener('voiceschanged', onVoicesChanged);
          startOnce();
        }, 1000);
        return;
      }
      speakNextChunk();
    };

    const speakViaBackend = async () => {
      try {
        const request = window.zyraAPI.requestBackend;
        if (!request) throw new Error('backend TTS bridge is unavailable');
        const reply = (await request('POST', '/api/speak', { text: response })) as
          { success?: boolean; error?: string } | null;
        if (stopped) return;
        if (!reply || reply.success === false) {
          throw new Error(reply?.error || 'backend rejected the speak request');
        }
        // Backend accepted the text and is speaking it with JennyNeural.
      } catch (err) {
        if (stopped) return;
        const reason = err instanceof Error ? err.message : String(err);
        setStatus(`Backend voice (JennyNeural) unavailable — using local voice. ${reason}`);
        speakViaLocalVoice();
      }
    };

    void speakViaBackend();
    return () => {
      stopped = true;
      if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    };
  }, [response]);

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
      if (payload.error) {
        setTranscript(heard);
        setResponse('');
        setError(`${payload.error}${reply ? ` ${reply}` : ''}`);
        setStatus('Voice control error');
        return;
      }

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
              <div className="voice-response-text">
                {response
                  .replace(/\r\n?/g, '\n')
                  .split(/\n{2,}|(?<=[.!?])\s+(?=[A-Z0-9•-])/)
                  .map((paragraph) => paragraph.trim())
                  .filter(Boolean)
                  .map((paragraph, paragraphIndex) => (
                    <p key={paragraphIndex}>{paragraph}</p>
                  ))}
              </div>
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
