import React, { useState, useRef, useEffect } from 'react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface ChatViewProps {
  setStatus: (status: string) => void;
}

const ChatView: React.FC<ChatViewProps> = ({ setStatus }) => {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: 'Hello! I am ZYRA. How can I help you today?' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [listening, setListening] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef('');
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Mirror the input into a ref so the voice stop handler can read the
  // latest recognized text without re-rendering.
  useEffect(() => {
    inputRef.current = input;
  }, [input]);

  // Stop any active voice session when the view unmounts.
  useEffect(() => () => {
    try { recognitionRef.current?.stop(); } catch { /* already stopped */ }
  }, []);

  const handleSend = async (textOverride?: string) => {
    const raw = textOverride !== undefined ? textOverride : input;
    if (!raw.trim() || loading) return;

    const userMessage = raw.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: userMessage }]);
    setLoading(true);

    // Real-time "Scan my network" requests run a local Nmap host discovery
    // on the backend — surface that while the scan is running.
    const isNetworkScan =
      /(scan (my|the) (local )?network|network scan|(show|discover|find) devices (on|of) (my |the )?network)/i
        .test(userMessage);
    setStatus(isNetworkScan ? 'Scanning your network...' : 'Thinking...');

    try {
      const response = await window.zyraAPI.aiChat(userMessage);
      setMessages((prev) => [...prev, { role: 'assistant', content: response }]);
      setStatus('Ready');
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' },
      ]);
      setStatus('Error');
    } finally {
      setLoading(false);
    }
  };

  // ===== ChatGPT-style voice input =====
  // Clicking the mic immediately starts listening (permission is requested on
  // first use) and continuously transcribes speech into the SAME chat input.
  // Clicking again stops listening and submits the recognized text through
  // the EXISTING handleSend() pipeline — identical to typed messages.
  const startVoice = () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: 'Voice input is not supported in this browser/runtime. Please type your message instead.',
      }]);
      setStatus('Voice input unavailable');
      return;
    }
    const base = inputRef.current.trim();
    let finalText = '';
    let interimText = '';
    let rec: any;
    try {
      rec = new SR();
    } catch (err: any) {
      setStatus('Voice input error');
      return;
    }
    recognitionRef.current = rec;
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = navigator.language || 'en-US';

    rec.onstart = () => {
      setListening(true);
      setStatus('Listening...');
    };

    rec.onresult = (event: any) => {
      interimText = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const res = event.results[i];
        if (res.isFinal) {
          const seg = String(res[0].transcript).trim();
          if (seg) finalText = finalText ? `${finalText} ${seg}` : seg;
        } else {
          interimText = String(res[0].transcript);
        }
      }
      const spacer = base && (finalText || interimText) ? ' ' : '';
      const joiner = finalText && interimText ? ' ' : '';
      setInput(base + spacer + finalText + joiner + interimText);
    };

    rec.onerror = (event: any) => {
      const code = event && event.error;
      if (code === 'no-speech') return; // silence is fine — keep listening
      recognitionRef.current = null;
      setListening(false);
      setStatus('Voice input error');
      const msg =
        code === 'not-allowed' || code === 'service-not-allowed'
          ? 'Microphone access was denied. Allow microphone permission for ZYRA and try again.'
          : code === 'audio-capture'
            ? 'No microphone was found. Please connect a microphone and try again.'
            : code === 'network'
              ? 'Speech recognition needs an internet connection. Please check your network and try again.'
              : `Voice input error: ${code}`;
      setMessages((prev) => [...prev, { role: 'assistant', content: msg }]);
      try { rec.stop(); } catch { /* already stopped */ }
    };

    rec.onend = () => {
      // Chromium auto-ends after silence pauses — restart while the user
      // still wants continuous listening (until they tap the mic again).
      if (recognitionRef.current === rec) {
        try { rec.start(); return; } catch { /* fall through */ }
        recognitionRef.current = null;
        setListening(false);
        setStatus('Ready');
      }
    };

    try {
      rec.start();
    } catch (err: any) {
      recognitionRef.current = null;
      setStatus('Voice input error');
    }
  };

  const stopVoice = (submit: boolean) => {
    const rec = recognitionRef.current;
    recognitionRef.current = null;
    setListening(false);
    setStatus('Ready');
    try { rec?.stop(); } catch { /* already stopped */ }
    if (submit) {
      const text = (inputRef.current || '').trim();
      if (text) handleSend(text);
    }
  };

  const toggleMic = () => {
    if (listening) {
      stopVoice(true);
    } else {
      startVoice();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (listening) stopVoice(false); // sending stops the voice session
      handleSend();
    }
  };

  return (
    <div className="chat-view">
      <div className="chat-messages">
        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.role}`}>
            <div className="message-avatar">
              {msg.role === 'assistant' ? '🤖' : '👤'}
            </div>
            <div className="message-content">
              <p style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</p>
            </div>
          </div>
        ))}
        {loading && (
          <div className="message assistant">
            <div className="message-avatar">🤖</div>
            <div className="message-content">
              <div className="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-input-area">
        <textarea
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={listening ? 'Listening... tap the mic to stop and send' : 'Type a message or ask me to do something...'}
          rows={2}
          disabled={loading}
        />
        <button
          className={`mic-button ${listening ? 'listening' : ''}`}
          onClick={toggleMic}
          disabled={loading}
          title={listening ? 'Stop voice input and send' : 'Voice input'}
          aria-label="Voice input"
        >
          {listening ? '⏹' : '🎤'}
        </button>
        <button
          className="send-button"
          onClick={() => handleSend()}
          disabled={loading || !input.trim()}
        >
          {loading ? '...' : 'Send'}
        </button>
      </div>
    </div>
  );
};

export default ChatView;
