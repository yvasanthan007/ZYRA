import React, { useState } from 'react';

interface LinkAnalysisResult {
  url?: string;
  verdict?: string;
  risk_score?: string;
  recommendation?: string;
  source?: string;
}

const LinkAnalyzer: React.FC = () => {
  const [url, setUrl] = useState('');
  const [analyzedUrl, setAnalyzedUrl] = useState('');
  const [result, setResult] = useState<LinkAnalysisResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const handleAnalyze = async () => {
    const target = url.trim();
    if (!target || busy) return;
    setBusy(true);
    setError('');
    setResult(null);
    // Echo the exact input being analyzed (safely escaped by React).
    setAnalyzedUrl(target);
    try {
      const raw = await window.zyraAPI.analyzeLink(target);
      // Guard: a resolved `{success:false, error}` payload (bridge-style
      // failure) must surface as an error, not an empty result.
      const status = raw as { success?: boolean; error?: string } | null;
      if (status && status.success === false) {
        setError(status.error || 'Link analysis failed');
        return;
      }
      const payload = (raw as { analysis?: LinkAnalysisResult })?.analysis
        ?? (raw as { data?: LinkAnalysisResult })?.data
        ?? (raw as LinkAnalysisResult);
      setResult({ ...payload, url: payload?.url ?? target });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Link analysis failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="link-analyzer">
      <h3>Phishing Link Analyzer</h3>
      <p className="voice-hint">
        Paste or type a URL, then Analyze. The exact input shown below is what
        gets analyzed — links are never opened automatically.
      </p>
      <div className="chat-input-area">
        <textarea
          className="chat-input"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/login"
          rows={2}
          disabled={busy}
          aria-label="URL to analyze"
        />
        <button
          className="send-button"
          onClick={handleAnalyze}
          disabled={busy || !url.trim()}
        >
          {busy ? '...' : 'Analyze'}
        </button>
      </div>
      {analyzedUrl && (
        <div className="transcript-item">
          <span className="transcript-label">Analyzing:</span>
          <p>{analyzedUrl}</p>
        </div>
      )}
      {error && (
        <p className="voice-hint" role="alert">{error}</p>
      )}
      {result && (
        <div className="voice-transcript-area">
          <div className="transcript-item">
            <span className="transcript-label">Verdict:</span>
            <p>{result.verdict ?? '—'}</p>
          </div>
          <div className="transcript-item">
            <span className="transcript-label">Risk:</span>
            <p>{result.risk_score ?? '—'}</p>
          </div>
          {result.recommendation && (
            <div className="transcript-item">
              <span className="transcript-label">Recommendation:</span>
              <p>{result.recommendation}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default LinkAnalyzer;
