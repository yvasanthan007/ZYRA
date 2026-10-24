import React, { useCallback, useEffect, useState } from 'react';

type DatasetRow = { sample_id: string; url: string; label: string; split: string; features: Record<string, number>; prediction: string | null; risk_score: number | null; correct: boolean | null };
type DatasetPage = { summary: { source: string; dataset_version: string; record_count: number; class_balance: Record<string, number>; missing_values: Record<string, number>; duplicate_urls: number; split_counts: Record<string, number>; predictions_evaluated: boolean }; total: number; page: number; page_size: number; records: DatasetRow[] };
type EvaluationInfo = {
  dataset_version?: string;
  test_set_size?: number;
  test_metrics?: {
    precision?: number; recall?: number; f1?: number;
    confusion_matrix?: { tn?: number; fp?: number; fn?: number; tp?: number };
  };
};
const DatasetExplorer: React.FC = () => {
  const [data, setData] = useState<DatasetPage | null>(null);
  const [modelInfo, setModelInfo] = useState<{evaluation?: EvaluationInfo; note?: string} | null>(null);
  useEffect(() => {
    const request = window.zyraAPI.requestBackend;
    if (!request) return;
    void request('GET', '/api/ml/phishing/model').then((raw: unknown) => {
      const response = raw as {success?: boolean; data?: typeof modelInfo};
      if (response.success) setModelInfo(response.data ?? null);
    }).catch(() => setModelInfo(null));
  }, []);
  const [search, setSearch] = useState(''); const [label, setLabel] = useState('all'); const [split, setSplit] = useState('all');
  const [page, setPage] = useState(1); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const load = useCallback(async (pageNumber: number) => {
    setBusy(true); setError('');
    try {
      const query = new URLSearchParams({ search, label, split, page: String(pageNumber), page_size: '20' });
      const response = await window.zyraAPI.requestBackend?.('GET', `/api/ml/phishing/dataset?${query.toString()}`) as { success?: boolean; data?: DatasetPage; error?: string };
      if (!response?.success || !response.data) throw new Error(response?.error || 'Dataset API returned no data.');
      setData(response.data); setPage(pageNumber);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to load labeled dataset.'); }
    finally { setBusy(false); }
  }, [search, label, split]);
  useEffect(() => { void load(1); }, [load]);
  return <section className="dataset-explorer">
    <h3>Dataset explorer</h3>
    <p className="voice-hint">Training corpus records are distinct from hold-out evaluation and live URL scans. Test rows are never used for training.</p>
    {modelInfo?.evaluation?.test_metrics && <div className="dataset-summary"><span>Held-out {modelInfo.evaluation.dataset_version} ({modelInfo.evaluation.test_set_size} records)</span><span>Precision {modelInfo.evaluation.test_metrics.precision} · Recall {modelInfo.evaluation.test_metrics.recall} · F1 {modelInfo.evaluation.test_metrics.f1}</span><span>Confusion: TN {modelInfo.evaluation.test_metrics.confusion_matrix?.tn}, FP {modelInfo.evaluation.test_metrics.confusion_matrix?.fp}, FN {modelInfo.evaluation.test_metrics.confusion_matrix?.fn}, TP {modelInfo.evaluation.test_metrics.confusion_matrix?.tp}</span></div>}
    {data && <div className="dataset-summary">
      <span><b>{data.summary.record_count.toLocaleString()}</b> records · {data.summary.dataset_version}</span>
      <span>Source: {data.summary.source}</span>
      <span>Legitimate {data.summary.class_balance.legitimate} / Phishing {data.summary.class_balance.phishing}</span>
      <span>Splits: train {data.summary.split_counts.train}, validation {data.summary.split_counts.validation}, test {data.summary.split_counts.test}</span>
      <span>Missing {Object.values(data.summary.missing_values).reduce((a, b) => a + b, 0)} · duplicate URLs {data.summary.duplicate_urls}</span>
      <span>Live analyses remain separately recorded as split=live; they are not included as training labels.</span>
    </div>}
    <div className="dataset-filters">
      <input aria-label="Search URLs or sample IDs" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search URL or sample ID" />
      <select aria-label="Filter by ground truth" value={label} onChange={e => setLabel(e.target.value)}><option value="all">All labels</option><option value="legitimate">Legitimate</option><option value="phishing">Phishing</option></select>
      <select aria-label="Filter by dataset split" value={split} onChange={e => setSplit(e.target.value)}><option value="all">All splits</option><option value="train">Train</option><option value="validation">Validation</option><option value="test">Test</option><option value="live">Live analysis</option></select>
    </div>
    {error && <p role="alert" className="voice-hint">{error}</p>}
    {busy && <p className="voice-hint">Loading actual labeled records…</p>}
    {data && <><div className="dataset-table-wrap"><table className="dataset-table"><thead><tr><th>Sample / URL</th><th>Ground truth</th><th>Split</th><th>Prediction / risk</th><th>Correct</th><th>Feature values</th></tr></thead><tbody>
      {data.records.map(row => <tr key={row.sample_id}><td><small>{row.sample_id}</small><br/><code>{row.url}</code></td><td>{row.label}</td><td>{row.split}</td><td>{row.prediction ?? 'Not evaluated'}{row.risk_score !== null ? ` · ${row.risk_score.toFixed(1)}%` : ''}</td><td>{row.correct === null ? '—' : row.correct ? 'Yes' : 'No'}</td><td><details><summary>{Object.keys(row.features).length} features</summary><pre>{JSON.stringify(row.features, null, 2)}</pre></details></td></tr>)}
    </tbody></table></div><div className="dataset-pagination"><span>{data.total.toLocaleString()} matching records · page {page}</span><button disabled={busy || page <= 1} onClick={() => void load(page - 1)}>Previous</button><button disabled={busy || page * data.page_size >= data.total} onClick={() => void load(page + 1)}>Next</button></div></>}
  </section>;
};
export default DatasetExplorer;
