import React, { useState } from 'react';
import DatasetExplorer from './DatasetExplorer';

interface CyberLLMData {
  url: string;
  prediction: 'PHISHING' | 'LEGITIMATE';
  phishing_score: number;
  score_is_calibrated_probability: boolean;
  disclaimer?: string;
}

interface CyberLLMResponse {
  success?: boolean;
  provider?: string;
  advisory_only?: boolean;
  data?: CyberLLMData;
  error?: string;
}

interface BackendResponse {
  ok?: boolean;
  status?: number;
  body?: unknown;
  error?: string | null;
}

const LinkAnalyzer: React.FC = () => {
  const [url, setUrl] = useState('');
  const [analyzedUrl, setAnalyzedUrl] = useState('');
  const [result, setResult] = useState<CyberLLMData | null>(null);
  const [provider, setProvider] = useState('CyberLLM');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<'analysis' | 'dataset'>('analysis');

  const analyzeWithCyberLLM = async (target: string): Promise<void> => {
    const request = window.zyraAPI?.requestBackend;

    if (!request) {
      throw new Error(
        'Zyra backend bridge is unavailable. Restart Zyra and try again.'
      );
    }

    const raw = await request(
      'POST',
      '/api/cyberllm/phishing',
      { url: target }
    );

    const wrapped = raw as BackendResponse;

    if (!wrapped || wrapped.ok !== true) {
      throw new Error(
        wrapped?.error ||
          `Zyra backend request failed (HTTP ${wrapped?.status ?? 'unknown'}).`
      );
    }

    const response = wrapped.body as CyberLLMResponse;

    if (!response || response.success !== true || !response.data) {
      throw new Error(
        response?.error ||
          'CyberLLM analysis failed. No verdict was produced.'
      );
    }

    const data = response.data;

    if (data.url !== target) {
      throw new Error(
        'The backend returned a different URL. The result was not displayed.'
      );
    }

    if (
      data.prediction !== 'PHISHING' &&
      data.prediction !== 'LEGITIMATE'
    ) {
      throw new Error('CyberLLM returned an unrecognized prediction.');
    }

    if (
      typeof data.phishing_score !== 'number' ||
      !Number.isFinite(data.phishing_score)
    ) {
      throw new Error('CyberLLM returned an invalid phishing score.');
    }

    setProvider(response.provider || 'CyberLLM');
    setAnalyzedUrl(target);
    setResult(data);
  };

  const handleAnalyze = async (capture = false): Promise<void> => {
    const target = url.trim();

    if (!capture && !target) {
      setError('Enter a URL before starting the analysis.');
      setResult(null);
      return;
    }

    if (busy) {
      return;
    }

    setBusy(true);
    setError('');
    setResult(null);
    setAnalyzedUrl(capture ? 'Capturing screen URL...' : target);

    try {
      let targetUrl = target;

      if (capture) {
        const captureFunction = window.zyraAPI?.captureAndAnalyzeLink;

        if (!captureFunction) {
          throw new Error(
            'Screen URL capture is unavailable in this Zyra build.'
          );
        }

        const captured = await captureFunction();

        if (!captured) {
          throw new Error(
            'No URL was captured. Copy a URL into the input field and try again.'
          );
        }

        targetUrl = String(captured).trim();

        if (!targetUrl) {
          throw new Error('The captured URL is empty.');
        }

        setUrl(targetUrl);
        setAnalyzedUrl(targetUrl);
      }

      let parsedUrl: URL;

      try {
        parsedUrl = new URL(targetUrl);
      } catch {
        throw new Error(
          'Enter a valid URL, including https:// or http://.'
        );
      }

      if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
        throw new Error('Only HTTP and HTTPS URLs can be analyzed.');
      }

      await analyzeWithCyberLLM(targetUrl);
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : 'An unexpected error occurred during URL analysis.';

      setError(message);
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="voice-panel">
      <div className="voice-header">
        <div>
          <h2>CyberLLM Link Analyzer</h2>
          <p className="voice-hint">
            Analyze URLs using your CyberLLM phishing detection service.
          </p>
        </div>
      </div>

      <div className="voice-tabs">
        <button
          type="button"
          className={tab === 'analysis' ? 'active' : ''}
          onClick={() => setTab('analysis')}
        >
          Link Analysis
        </button>

        <button
          type="button"
          className={tab === 'dataset' ? 'active' : ''}
          onClick={() => setTab('dataset')}
        >
          Dataset Explorer
        </button>
      </div>

      {tab === 'dataset' ? (
        <DatasetExplorer />
      ) : (
        <>
          <div className="voice-input-area">
            <label htmlFor="cyberllm-url">
              Website URL
            </label>

            <input
              id="cyberllm-url"
              type="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://example.com"
              disabled={busy}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !busy) {
                  void handleAnalyze(false);
                }
              }}
            />

            <div className="voice-actions">
              <button
                type="button"
                onClick={() => void handleAnalyze(false)}
                disabled={busy || !url.trim()}
              >
                {busy ? 'Analyzing...' : 'Analyze with CyberLLM'}
              </button>

              <button
                type="button"
                onClick={() => void handleAnalyze(true)}
                disabled={busy}
              >
                Capture Screen URL
              </button>
            </div>

            <p className="voice-hint">
              The URL is submitted to your configured Zyra backend, which
              forwards the analysis request to CyberLLM.
            </p>
          </div>

          {analyzedUrl && (
            <div className="transcript-item">
              <span className="transcript-label">
                URL submitted for analysis:
              </span>
              <p>{analyzedUrl}</p>
            </div>
          )}

          {error && (
            <p className="voice-hint" role="alert">
              {error}
            </p>
          )}

          {result && (
            <div className="voice-transcript-area">
              <div className="transcript-item">
                <span className="transcript-label">
                  Analysis provider:
                </span>
                <p>{provider}</p>
              </div>

              <div className="transcript-item">
                <span className="transcript-label">
                  CyberLLM prediction:
                </span>
                <p>{result.prediction}</p>
              </div>

              <div className="transcript-item">
                <span className="transcript-label">
                  Phishing score (uncalibrated):
                </span>
                <p>
                  {result.phishing_score}
                  {result.phishing_score >= 0 &&
                  result.phishing_score <= 1
                    ? ` (${(result.phishing_score * 100).toFixed(2)} on a 0–100 display scale)`
                    : ''}
                </p>
              </div>

              <div className="transcript-item">
                <span className="transcript-label">
                  Calibrated probability:
                </span>
                <p>
                  {result.score_is_calibrated_probability
                    ? 'Reported as calibrated by the API'
                    : 'No — this is an uncalibrated model score.'}
                </p>
              </div>

              <div className="transcript-item">
                <span className="transcript-label">
                  Assessment disclaimer:
                </span>
                <p>
                  {result.disclaimer ||
                    'This model assessment is not a guarantee of safety. False positives and false negatives are possible.'}
                </p>
              </div>

              <p className="voice-hint">
                Security notice: A LEGITIMATE prediction does not prove
                that a website is safe. Verify suspicious links independently
                before entering credentials or sensitive information.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default LinkAnalyzer;