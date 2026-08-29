import React, { useState, useEffect } from 'react';

interface SystemMonitorProps {
  setStatus: (status: string) => void;
}

interface MetricState {
  analysis?: { status: string; description: string; level: string };
  cpu: { percent: number; cores_logical: number; cores_physical: number; bar: string };
  memory: { percent: number; used_str: string; available_str: string; total_str: string; bar: string };
  disk: { percent: number; used_str: string; free_str: string; total_str: string; bar: string };
  network: { download_speed_str: string; upload_speed_str: string; total_recv_str: string; total_sent_str: string };
  battery: { has_battery: boolean; percent_str: string; charging_str: string };
  uptime: { formatted: string };
  system: { formatted: string };
}

const SystemMonitor: React.FC<SystemMonitorProps> = ({ setStatus }) => {
  const [metrics, setMetrics] = useState<MetricState | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setStatus('System Monitor active');
    let isMounted = true;

    const fetchMetrics = async () => {
      try {
        if (window.zyraAPI && window.zyraAPI.getSystemMetrics) {
          const res = await window.zyraAPI.getSystemMetrics();
          if (isMounted) {
            const data = res && res.data ? res.data : res;
            if (data && data.cpu) {
              setMetrics(data);
              setError(null);
            }
          }
        }
      } catch (err: any) {
        if (isMounted) {
          setError('Failed to fetch metrics');
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 1500);

    return () => {
      isMounted = false;
      clearInterval(interval);
      setStatus('Ready');
    };
  }, []);

  if (loading && !metrics) {
    return <div className="loading-state">Loading system metrics...</div>;
  }

  if (error && !metrics) {
    return <div className="error-state">{error}</div>;
  }

  return (
    <div className="system-monitor-view" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontSize: '18px', fontWeight: 'bold', color: 'var(--accent, #ff8844)', letterSpacing: '1px' }}>
          SYSTEM MONITOR
        </h2>
        <span style={{ fontSize: '12px', padding: '3px 8px', borderRadius: '10px', background: 'rgba(0, 255, 136, 0.15)', color: '#00ff88', fontWeight: 'bold' }}>
          LIVE
        </span>
      </div>

      {/* Live System Health Analysis */}
      <div className="metric-box" style={{
        background: 'rgba(14, 14, 30, 0.85)',
        padding: '12px 14px',
        borderRadius: '8px',
        border: '1px solid var(--border-color, #2a2a4a)',
        borderLeft: `4px solid ${
          metrics?.analysis?.level === 'warning' ? '#ff5555' :
          metrics?.analysis?.level === 'elevated' ? '#ffaa00' :
          metrics?.analysis?.level === 'low' ? '#00ccff' : '#00ff88'
        }`,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
          <strong style={{ fontSize: '12px', letterSpacing: '1px', textTransform: 'uppercase', color: '#ffaa55' }}>System Status</strong>
          <span style={{
            fontSize: '11px',
            fontWeight: 'bold',
            padding: '2px 7px',
            borderRadius: '6px',
            fontFamily: 'monospace',
            color: metrics?.analysis?.level === 'warning' ? '#ff5555' :
                   metrics?.analysis?.level === 'elevated' ? '#ffaa00' :
                   metrics?.analysis?.level === 'low' ? '#00ccff' : '#00ff88',
            background: 'rgba(255,255,255,0.08)'
          }}>
            {metrics?.analysis?.status || 'NORMAL'}
          </span>
        </div>
        <p style={{ fontSize: '12px', margin: 0, color: 'rgba(255, 200, 150, 0.85)', lineHeight: 1.4 }}>
          {metrics?.analysis?.description || 'CPU and memory usage are within normal ranges.'}
        </p>
      </div>

      {/* CPU */}
      <div className="metric-box" style={{ background: 'var(--bg-secondary, #16213e)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-color, #2a2a4a)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
          <strong>CPU</strong>
          <span style={{ fontFamily: 'monospace' }}>{metrics?.cpu ? `${Math.round(metrics.cpu.percent)}%` : '--%'}</span>
        </div>
        <div style={{ fontFamily: 'monospace', color: 'var(--accent, #ff8844)', fontSize: '14px', letterSpacing: '2px', marginBottom: '6px' }}>
          {metrics?.cpu?.bar || '░░░░░░░░░░'}
        </div>
        <div style={{ height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${Math.min(100, metrics?.cpu?.percent || 0)}%`, background: 'var(--accent, #ff8844)', transition: 'width 0.3s' }} />
        </div>
      </div>

      {/* Memory */}
      <div className="metric-box" style={{ background: 'var(--bg-secondary, #16213e)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-color, #2a2a4a)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
          <strong>Memory</strong>
          <span style={{ fontFamily: 'monospace' }}>{metrics?.memory ? `${Math.round(metrics.memory.percent)}%` : '--%'}</span>
        </div>
        <div style={{ fontFamily: 'monospace', color: 'var(--accent, #ff8844)', fontSize: '14px', letterSpacing: '2px', marginBottom: '6px' }}>
          {metrics?.memory?.bar || '░░░░░░░░░░'}
        </div>
        <div style={{ height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden', marginBottom: '6px' }}>
          <div style={{ height: '100%', width: `${Math.min(100, metrics?.memory?.percent || 0)}%`, background: 'var(--accent, #ff8844)', transition: 'width 0.3s' }} />
        </div>
        <small style={{ color: 'var(--text-secondary, #a0a0b0)' }}>{metrics?.memory?.used_str} used / {metrics?.memory?.total_str} total</small>
      </div>

      {/* Disk */}
      <div className="metric-box" style={{ background: 'var(--bg-secondary, #16213e)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-color, #2a2a4a)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
          <strong>Disk</strong>
          <span style={{ fontFamily: 'monospace' }}>{metrics?.disk ? `${Math.round(metrics.disk.percent)}%` : '--%'}</span>
        </div>
        <div style={{ fontFamily: 'monospace', color: 'var(--accent, #ff8844)', fontSize: '14px', letterSpacing: '2px', marginBottom: '6px' }}>
          {metrics?.disk?.bar || '░░░░░░░░░░'}
        </div>
        <div style={{ height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden', marginBottom: '6px' }}>
          <div style={{ height: '100%', width: `${Math.min(100, metrics?.disk?.percent || 0)}%`, background: 'var(--accent, #ff8844)', transition: 'width 0.3s' }} />
        </div>
        <small style={{ color: 'var(--text-secondary, #a0a0b0)' }}>{metrics?.disk?.used_str} used / {metrics?.disk?.free_str} free</small>
      </div>

      {/* Network */}
      <div className="metric-box" style={{ background: 'var(--bg-secondary, #16213e)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-color, #2a2a4a)' }}>
        <strong style={{ display: 'block', marginBottom: '8px' }}>Network</strong>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '4px' }}>
          <span>↓ Download</span>
          <span style={{ fontFamily: 'monospace' }}>{metrics?.network?.download_speed_str || '0 B/s'}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
          <span>↑ Upload</span>
          <span style={{ fontFamily: 'monospace' }}>{metrics?.network?.upload_speed_str || '0 B/s'}</span>
        </div>
      </div>

      {/* Battery */}
      <div className="metric-box" style={{ background: 'var(--bg-secondary, #16213e)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-color, #2a2a4a)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '4px' }}>
          <span>Battery</span>
          <span style={{ fontFamily: 'monospace' }}>{metrics?.battery?.percent_str || 'N/A'}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
          <span>Charging</span>
          <span style={{ fontFamily: 'monospace' }}>{metrics?.battery?.charging_str || 'No'}</span>
        </div>
      </div>

      {/* Uptime */}
      <div className="metric-box" style={{ background: 'var(--bg-secondary, #16213e)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-color, #2a2a4a)' }}>
        <strong style={{ display: 'block', marginBottom: '4px' }}>Uptime</strong>
        <span style={{ fontFamily: 'monospace' }}>{metrics?.uptime?.formatted || '0h 00m'}</span>
      </div>

      {/* System */}
      <div className="metric-box" style={{ background: 'var(--bg-secondary, #16213e)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-color, #2a2a4a)' }}>
        <strong style={{ display: 'block', marginBottom: '4px' }}>System</strong>
        <span>{metrics?.system?.formatted || 'Windows / Linux / macOS'}</span>
      </div>
    </div>
  );
};

export default SystemMonitor;
