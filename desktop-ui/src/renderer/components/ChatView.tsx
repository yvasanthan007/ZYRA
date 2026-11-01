import React, { useState, useRef, useEffect } from 'react';

interface RetrievedSource {
  title?: string;
  source?: string;
  url?: string;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
  source?: string;
  confidence?: number;
  retrievedSources?: RetrievedSource[];
}

interface ChatViewProps {
  setStatus: (status: string) => void;
}

interface AIChatResponse {
  answer?: string;
  response?: string;
  message?: string;
  source?: string;
  confidence?: number;
  retrieved_sources?: RetrievedSource[];
  retrievedSources?: RetrievedSource[];
  success?: boolean;
  error?: string;
}

function normalizeChatResponse(response: unknown): AIChatResponse {
  if (typeof response === 'string') {
    return { answer: response };
  }

  if (response === null || typeof response !== 'object') {
    return { answer: 'I received an empty or unsupported response.' };
  }

  const data = response as Record<string, unknown>;

  const retrievedSourcesValue =
    data.retrieved_sources ?? data.retrievedSources;

  const retrievedSources: RetrievedSource[] = Array.isArray(
    retrievedSourcesValue,
  )
    ? retrievedSourcesValue.filter(
        (item): item is RetrievedSource =>
          item !== null && typeof item === 'object',
      )
    : [];

  const confidenceValue = data.confidence;

  return {
    answer:
      typeof data.answer === 'string'
        ? data.answer
        : typeof data.response === 'string'
          ? data.response
          : typeof data.message === 'string'
            ? data.message
            : typeof data.error === 'string'
              ? data.error
              : 'I could not generate a response.',
    source: typeof data.source === 'string' ? data.source : undefined,
    confidence:
      typeof confidenceValue === 'number' &&
      Number.isFinite(confidenceValue)
        ? confidenceValue
        : undefined,
    retrieved_sources: retrievedSources,
    success: typeof data.success === 'boolean' ? data.success : undefined,
    error: typeof data.error === 'string' ? data.error : undefined,
  };
}

const ChatView: React.FC<ChatViewProps> = ({ setStatus }) => {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: 'Hello! I am ZYRA. How can I help you today?',
    },
  ]);

  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleSend = async (): Promise<void> => {
    const userMessage = input.trim();

    if (!userMessage || loading) {
      return;
    }

    setInput('');

    setMessages((previous) => [
      ...previous,
      { role: 'user', content: userMessage },
    ]);

    setLoading(true);
    setStatus('Thinking...');

    try {
      const rawResponse: unknown =
        await window.zyraAPI.aiChat(userMessage);

      const response = normalizeChatResponse(rawResponse);

      setMessages((previous) => [
        ...previous,
        {
          role: 'assistant',
          content: response.answer || 'I could not generate a response.',
          source: response.source,
          confidence: response.confidence,
          retrievedSources: response.retrieved_sources,
        },
      ]);

      setStatus(response.success === false ? 'Error' : 'Ready');
    } catch (error: unknown) {
      const errorMessage =
        error instanceof Error ? error.message : 'Unknown error';

      console.error('[ZYRA Chat] Request failed:', errorMessage);

      setMessages((previous) => [
        ...previous,
        {
          role: 'assistant',
          content:
            'Sorry, I encountered an error while contacting the AI backend. Please check that the Zyra backend is running and try again.',
        },
      ]);

      setStatus('Error');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (
    event: React.KeyboardEvent<HTMLTextAreaElement>,
  ): void => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  };

  return (
    <div className="chat-view">
      <div className="chat-messages">
        {messages.map((message, index) => (
          <div
            key={index}
            className={`message ${message.role}`}
          >
            <div className="message-avatar">
              {message.role === 'assistant' ? '🤖' : '👤'}
            </div>

            <div className="message-content">
              {message.role === 'assistant' ? (
                <div className="message-text">
                  {message.content
                    .replace(/\r\n?/g, '\n')
                    .split(/\n{2,}|(?<=[.!?])\s+(?=[A-Z0-9•-])/)
                    .map((paragraph) => paragraph.trim())
                    .filter(Boolean)
                    .map((paragraph, paragraphIndex) => (
                      <p key={paragraphIndex}>{paragraph}</p>
                    ))}
                </div>
              ) : (
                <p className="message-text">{message.content}</p>
              )}

              {message.role === 'assistant' && message.source && (
                <div className="message-source">
                  Evidence source: {message.source}
                  {message.confidence !== undefined
                    ? ` · confidence ${message.confidence.toFixed(2)}`
                    : ''}

                  {!!message.retrievedSources?.length && (
                    <ul>
                      {message.retrievedSources.map(
                        (item, sourceIndex) => (
                          <li
                            key={`${item.title ?? item.source ?? 'source'}-${sourceIndex}`}
                          >
                            {item.title || item.source || 'Source'}
                            {item.url ? ` — ${item.url}` : ''}
                          </li>
                        ),
                      )}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="message assistant">
            <div className="message-avatar">🤖</div>
            <div className="message-content">
              <div className="typing-indicator">
                <span />
                <span />
                <span />
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
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message or ask me to do something..."
          rows={2}
          disabled={loading}
        />

        <button
          className="send-button"
          onClick={() => void handleSend()}
          disabled={loading || !input.trim()}
        >
          {loading ? '...' : 'Send'}
        </button>
      </div>
    </div>
  );
};

export default ChatView;