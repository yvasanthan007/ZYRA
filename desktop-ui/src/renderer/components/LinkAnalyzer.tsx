import React, { useState } from 'react';
import DatasetExplorer from './DatasetExplorer';

interface LinkAnalysisResult {
  url?: string;
  verdict?: string;
  risk_score?: number | string;
  phishing_probability?: number | null;
  analysis_time_ms?: number;
  prediction?: string;
  algorithm?: string;
  model_version?: string;
  analyzed_at?: string;
  model_status?: string;
  probabilities_calibrated?: boolean;
  features?: Record<string, number>;
  explanation?: { available?: boolean; method?: string; note?: string; disclaimer?: string; contributions?: Array<{feature: string; value: number; contribution: number; direction: string; description: string}> };
  global_feature_importance?: Array<{feature: string; importance: number; description: string}>;
  recommendation?: string;
  observations?: string[];
  reasoning?: string[];
  findings?: Array<{id?: string; title?: string; detail?: string; matched_keywords?: Array<{keyword: string; category: string; locations: string[]; weight: number}> }>;
}
interface ModelInfo {
  available?: boolean; algorithm?: string; version?: string; trained_at?: string; model_path?: string; note?: string;
  evaluation?: {
    dataset_version?: string; split_strategy?: string; test_set_size?: number;
    test_metrics?: {
      precision?: number; recall?: number; f1?: number;
      confusion_matrix?: { tn?: number; fp?: number; fn?: number; tp?: number };
    };
  };
}

const LinkAnalyzer: React.FC = () => {
  const [url, setUrl] = useState('');
  const [analyzedUrl, setAnalyzedUrl] = useState('');
  const [result, setResult] = useState<LinkAnalysisResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<'analysis' | 'dataset'>('analysis');
  const [lastAnalyzedAt, setLastAnalyzedAt] = useState('');
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
  React.useEffect(() => {
    const request = window.zyraAPI.requestBackend;
    if (!request) { setModelInfo({ available: false, note: 'Backend API is unavailable.' }); return; }
    void request('GET', '/api/ml/phishing/model').then((raw: unknown) => {
      const response = raw as { success?: boolean; data?: ModelInfo; error?: string };
      if (response?.success && response.data) setModelInfo(response.data);
      else setModelInfo({ available: false, note: response?.error || 'Model metadata unavailable.' });
    }).catch((err: unknown) => setModelInfo({ available: false, note: err instanceof Error ? err.message : 'Backend unavailable.' }));
  }, []);

  const handleAnalyze = async (capture = false) => {
    const target = url.trim();
    if (!capture && !target) { setError('Enter a URL or use Capture screen URL. No safety verdict was made.'); setResult(null); return; }
    if (busy) return;
    setBusy(true);
    setError('');
    setResult(null);
    setAnalyzedUrl(capture ? 'Capturing a fresh screen URL…' : target);
    try {
      const raw = capture
        ? await window.zyraAPI.captureAndAnalyzeLink?.()
        : await window.zyraAPI.analyzeLink(target);
      // Guard: a resolved `{success:false, error}` payload (bridge-style
      // failure) must surface as an error, not an empty result.
      const status = raw as { success?: boolean; error?: string } | null;
      if (status && status.success === false) {
        setError(status.error || 'Link analysis failed; no safety verdict was made.');
        return;
      }
      const payload = (raw as { analysis?: LinkAnalysisResult })?.analysis
        ?? (raw as { data?: LinkAnalysisResult })?.data
        ?? (raw as LinkAnalysisResult);
      const analyzedTarget = capture ? payload?.url : target;
      if (!payload || typeof payload !== 'object' || typeof payload.verdict !== 'string') {
        setError('Link analysis returned no valid verdict. Treat this URL as unverified.');
        return;
      }
      if (!analyzedTarget || (payload.url && payload.url !== analyzedTarget)) {
        setError('Backend analyzed a different URL than the one entered. No result was displayed.');
        return;
      }
      setLastAnalyzedAt(payload.analyzed_at ?? new Date().toISOString());
      setAnalyzedUrl(analyzedTarget);
      setResult({ ...payload, url: payload.url ?? analyzedTarget });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Link analysis failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="link-analyzer">
      <h3>Phishing Link Analyzer</h3>
      <div className="dataset-filters"><button onClick={() => setTab('analysis')} aria-pressed={tab === 'analysis'}>URL risk analysis</button><button onClick={() => setTab('dataset')} aria-pressed={tab === 'dataset'}>Dataset explorer</button></div>
      {tab === 'dataset' ? <DatasetExplorer /> : <>
      <section className="dataset-summary" aria-label="Model evaluation">
        <span><b>Model status:</b> {modelInfo?.available ? `${modelInfo.algorithm} v${modelInfo.version} loaded` : modelInfo?.note ?? 'Checking model…'}</span>
        {modelInfo?.evaluation?.test_metrics && <><span>Dataset {modelInfo.evaluation.dataset_version} · {modelInfo.evaluation.split_strategy}</span><span>Held-out test size {modelInfo.evaluation.test_set_size}</span><span>Precision {modelInfo.evaluation.test_metrics.precision} · Recall {modelInfo.evaluation.test_metrics.recall} · F1 {modelInfo.evaluation.test_metrics.f1}</span><span>Confusion matrix TN {modelInfo.evaluation.test_metrics.confusion_matrix?.tn}, FP {modelInfo.evaluation.test_metrics.confusion_matrix?.fp}, FN {modelInfo.evaluation.test_metrics.confusion_matrix?.fn}, TP {modelInfo.evaluation.test_metrics.confusion_matrix?.tp}</span></>}
        {!modelInfo?.evaluation?.test_metrics && <span>Held-out evaluation metrics unavailable.</span>}
      </section>
      <p className="voice-hint">
        Paste or type a URL, then Analyze. Or explicitly capture the current screen. The exact URL returned is checked below; links are never opened automatically.
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
          onClick={() => void handleAnalyze(false)}
          disabled={busy}
        >
          {busy ? '...' : 'Analyze'}
        </button>
        <button className="send-button" onClick={() => void handleAnalyze(true)} disabled={busy}>Capture screen URL</button>
      </div>
      {analyzedUrl && (
        <div className="transcript-item">
          <span className="transcript-label">Analyzing:</span>
          <p>{analyzedUrl}</p>
        </div>
      )}
      {error && (
        <p className="voice-hint" role="alert">{error} No URL is considered safe when analysis fails.</p>
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
          {result.phishing_probability !== null && result.phishing_probability !== undefined && (
            <div className="transcript-item">
              <span className="transcript-label">XGBoost phishing probability (uncalibrated):</span>
              <p>{(result.phishing_probability * 100).toFixed(2)}% · risk score {Number(result.risk_score ?? result.phishing_probability * 100).toFixed(1)}/100</p>
            </div>
          )}
          <div className="transcript-item"><span className="transcript-label">Model / status / prediction:</span><p>{result.algorithm ?? 'Unavailable'} {result.model_version ? `v${result.model_version}` : ''} · {result.prediction ?? 'unavailable'} · {result.model_status ?? (result.phishing_probability == null ? 'model status unavailable' : 'loaded')}</p></div>
          {lastAnalyzedAt && <div className="transcript-item"><span className="transcript-label">Analyzed at / duration:</span><p>{lastAnalyzedAt}{result.analysis_time_ms !== undefined ? ` · ${result.analysis_time_ms} ms` : ''}</p></div>}
          {result.explanation && <div className="transcript-item"><span className="transcript-label">Individual URL explanation:</span><p>{result.explanation.available ? result.explanation.method : result.explanation.note}</p>{result.explanation.available && <ul>{result.explanation.contributions?.map(item => <li key={item.feature}><b>{item.description}</b> = {item.value}; {item.direction} (margin contribution {item.contribution.toFixed(3)}). This is a model contribution, not proof of maliciousness.</li>)}</ul>}</div>}
          {!!result.findings?.filter(item => item.id === 'phishing_keyword_signals').length && <div className="transcript-item"><span className="transcript-label">Matched phishing-related keywords:</span><ul>{result.findings.filter(item => item.id === 'phishing_keyword_signals').map((item, index) => <li key={`${item.id}-${index}`}>{item.detail}</li>)}</ul></div>}
          {!!result.reasoning?.length && <div className="transcript-item"><span className="transcript-label">Risk reasoning:</span><ul>{result.reasoning.map((reason, index) => <li key={`${index}-${reason}`}>{reason}</li>)}</ul></div>}
          {result.features && <details className="transcript-item"><summary>Exact feature values passed to XGBoost ({Object.keys(result.features).length})</summary><pre>{JSON.stringify(result.features, null, 2)}</pre></details>}
          {!!result.global_feature_importance?.length && <details className="transcript-item"><summary>Global XGBoost feature importance (separate from this URL)</summary><ol>{result.global_feature_importance.slice(0, 10).map(item => <li key={item.feature}>{item.description}: {item.importance.toFixed(4)}</li>)}</ol></details>}
          <p className="voice-hint">The shipped model uses synthetic seed patterns, not independently verified real-world labels. Its probabilities are uncalibrated model scores and are not verified real-world risk estimates.</p>
          {result.recommendation && (
            <div className="transcript-item">
              <span className="transcript-label">Recommendation:</span>
              <p>{result.recommendation}</p>
            </div>
          )}
        </div>
      )}
      </>}
    </div>
  );
};

export default LinkAnalyzer;
