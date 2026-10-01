// ===== URL ANALYZER CONTROLLER =====
const urlCard = document.getElementById('url-analyzer-card');
const btnToggleUrl = document.getElementById('btn-toggle-url');
const btnCloseUrl = document.getElementById('url-close-btn');
const urlInput = document.getElementById('url-input');
const urlAnalyzeBtn = document.getElementById('url-analyze-btn');
const urlBadge = document.getElementById('url-badge');
const urlBody = document.getElementById('url-body');

const urlStagesSection = document.getElementById('url-stages-section');
const urlStagesEl = document.getElementById('url-stages');
const urlStageLabel = document.getElementById('url-stage-label');
const urlProgressVal = document.getElementById('url-progress-val');
const urlProgressBar = document.getElementById('url-progress-bar');

const urlResultSection = document.getElementById('url-result-section');
const urlScoreEl = document.getElementById('url-score');
const urlRiskLabel = document.getElementById('url-risk-label');
const urlClassLabel = document.getElementById('url-class-label');
const urlTargetEl = document.getElementById('url-target');

const urlSummarySection = document.getElementById('url-summary-section');
const urlChecksEl = document.getElementById('url-checks');
const urlDetailsSection = document.getElementById('url-details-section');
const urlDetailsEl = document.getElementById('url-details');
const urlSslSection = document.getElementById('url-ssl-section');
const urlSslEl = document.getElementById('url-ssl');
const urlThreatSection = document.getElementById('url-threat-section');
const urlThreatEl = document.getElementById('url-threat');
const urlFindingsSection = document.getElementById('url-findings-section');
const urlFindingsEl = document.getElementById('url-findings');
const urlRecSection = document.getElementById('url-recommendation-section');
const urlRecEl = document.getElementById('url-recommendation');
const urlActionsEl = document.getElementById('url-actions');
const urlReportBtn = document.getElementById('url-report-btn');
const urlDownloadBtn = document.getElementById('url-download-btn');

const urlHistorySection = document.getElementById('url-history-section');
const urlHistoryEl = document.getElementById('url-history');
const urlHistoryEmpty = document.getElementById('url-history-empty');

const urlErrorCard = document.getElementById('url-error-card');
const urlErrorReason = document.getElementById('url-error-reason');

let isUrlOpen = false;
let urlScanId = null;
let urlStagesMap = {};      // key -> stage row element
let urlLastChatScan = null; // scan_id whose chat ack was already shown
let urlReportReady = false; // report generated for current scan

const URL_TRIGGER_PHRASES = [
  'analyze', 'analyse', 'check this url', 'check the url', 'check url',
  'check whether', 'is this website', 'is this link', 'is this site',
  'scan this url', 'scan the url', 'scan url', 'check this website',
  'check this site', 'phishing', 'is it safe', 'is this safe',
  'malicious', 'for threats', 'this link safe', 'website safe',
];
const URL_BARE_RE = /(https?:\/\/|www\.)\S+/i;

function isUrlRequest(lowerText) {
  if (URL_BARE_RE.test(lowerText)) {
    return URL_TRIGGER_PHRASES.some(function (p) { return lowerText.includes(p); })
      || /\b(url|link|website|site)\b/.test(lowerText);
  }
  return URL_TRIGGER_PHRASES.some(function (p) { return lowerText.includes(p); })
    && /\b(url|link|website|site|this|that|it)\b/.test(lowerText);
}

function openUrlPanel() {
  isUrlOpen = true;
  if (urlCard) urlCard.classList.add('visible');
  if (btnToggleUrl) btnToggleUrl.classList.add('active');
}
function closeUrlPanel() {
  isUrlOpen = false;
  if (urlCard) urlCard.classList.remove('visible');
  if (btnToggleUrl) btnToggleUrl.classList.remove('active');
}
if (btnToggleUrl) {
  btnToggleUrl.addEventListener('click', function () {
    if (isUrlOpen) closeUrlPanel(); else openUrlPanel();
  });
}
if (btnCloseUrl) btnCloseUrl.addEventListener('click', closeUrlPanel);

function setUrlBadge(text, cls) {
  if (!urlBadge) return;
  urlBadge.textContent = text;
  urlBadge.classList.remove('offline');
  if (cls === 'offline') urlBadge.classList.add('offline');
}

function showUrlError(reason) {
  if (urlErrorCard) urlErrorCard.classList.add('visible');
  if (urlErrorReason) urlErrorReason.textContent = reason || 'URL analysis could not be completed.';
  setUrlBadge('ERROR', 'offline');
  if (urlAnalyzeBtn) { urlAnalyzeBtn.disabled = false; urlAnalyzeBtn.classList.remove('scanning'); }
}
function clearUrlError() {
  if (urlErrorCard) urlErrorCard.classList.remove('visible');
  if (urlErrorReason) urlErrorReason.textContent = '';
}

function resetUrlResultSections() {
  [urlStagesSection, urlResultSection, urlSummarySection, urlDetailsSection,
    urlSslSection, urlThreatSection, urlFindingsSection, urlRecSection,
    urlActionsEl].forEach(function (el) {
      if (el) el.style.display = 'none';
    });
  urlStagesMap = {};
  urlReportReady = false;
}

function buildUrlStages(stages) {
  if (!urlStagesEl) return;
  urlStagesEl.innerHTML = '';
  urlStagesMap = {};
  (stages || []).forEach(function (st) {
    const row = document.createElement('div');
    row.className = 'url-stage pending';
    row.innerHTML = '<span class="url-stage-icon">&#9675;</span><span>' + (st.label || st.key) + '</span>';
    urlStagesEl.appendChild(row);
    urlStagesMap[st.key] = row;
  });
}

function updateUrlStageRow(key, status, detail) {
  const row = urlStagesMap[key];
  if (!row) return;
  row.classList.remove('pending', 'running', 'done', 'fail', 'skip');
  row.classList.add(status);
  let icon = '&#9675;';
  if (status === 'done') icon = '&#10003;';
  else if (status === 'fail') icon = '&#10007;';
  else if (status === 'skip') icon = '&#8212;';
  else if (status === 'running') icon = '&#9654;';
  row.innerHTML = '<span class="url-stage-icon">' + icon + '</span><span>' + (detail || row.textContent.replace(/^.*?\s/, '')) + '</span>';
}

function setUrlButtonsEnabled(enabled) {
  if (urlReportBtn) urlReportBtn.disabled = !enabled;
  if (urlDownloadBtn) urlDownloadBtn.disabled = !enabled;
}

function urlDetailRow(k, v) {
  const val = (v === null || v === undefined || v === '') ? '—' : String(v);
  return '<div class="url-detail-row"><span class="url-detail-k">' + k + '</span><span class="url-detail-v">' + escapeHtml(val) + '</span></div>';
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function renderUrlResult(r) {
  if (!r) return;
  if (urlTargetEl) urlTargetEl.textContent = r.display_url || r.url || '—';

  const score = r.score;
  if (urlScoreEl) {
    urlScoreEl.textContent = score + ' / 100';
    urlScoreEl.classList.remove('safe', 'suspicious', 'danger');
    if (score >= 70) urlScoreEl.classList.add('safe');
    else if (score >= 40) urlScoreEl.classList.add('suspicious');
    else urlScoreEl.classList.add('danger');
  }
  if (urlRiskLabel) urlRiskLabel.textContent = 'RISK: ' + (r.risk_level_label || r.risk_level || '—');
  if (urlClassLabel) urlClassLabel.textContent = r.classification_summary || r.classification_label || '—';

  if (urlResultSection) urlResultSection.style.display = 'block';

  // Scan summary checklist
  const checks = (r.summary && r.summary.checks) || [];
  if (urlChecksEl) {
    urlChecksEl.innerHTML = checks.map(function (c) {
      const icons = { pass: '&#10003;', fail: '&#10007;', warn: '&#9888;', skip: '&#8212;' };
      return '<div class="url-check ' + c.status + '"><span class="url-check-icon">' + (icons[c.status] || '&#8212;') + '</span><span>' + escapeHtml(c.name) + (c.detail ? ' — ' + escapeHtml(c.detail) : '') + '</span></div>';
    }).join('');
  }
  if (urlSummarySection) urlSummarySection.style.display = checks.length ? 'block' : 'none';

  // URL details
  const ud = r.url_details || {};
  if (urlDetailsEl) {
    urlDetailsEl.innerHTML = [
      urlDetailRow('Protocol', ud.protocol),
      urlDetailRow('Domain', ud.domain),
      urlDetailRow('Registered Domain', ud.registered_domain),
      urlDetailRow('IP Address', ud.ip_address),
      urlDetailRow('Port', ud.port || (ud.protocol === 'HTTPS' ? 443 : 80)),
      urlDetailRow('Path', ud.path),
      urlDetailRow('Query', ud.query),
      urlDetailRow('Fragment', ud.fragment),
      urlDetailRow('Redirects', ud.redirects),
    ].join('');
  }
  if (urlDetailsSection) urlDetailsSection.style.display = 'block';

  // SSL / TLS
  const ssl = r.ssl || {};
  if (urlSslEl) {
    urlSslEl.innerHTML = [
      urlDetailRow('Status', ssl.status),
      urlDetailRow('HTTPS', ssl.https_enabled ? 'Enabled' : 'Disabled'),
      urlDetailRow('Valid', ssl.valid),
      urlDetailRow('Issuer', ssl.issuer),
      urlDetailRow('Subject', ssl.subject),
      urlDetailRow('Expires', ssl.expires),
      urlDetailRow('Expires In', ssl.expires_in_days != null ? ssl.expires_in_days + ' day(s)' : '—'),
      urlDetailRow('TLS Version', ssl.tls_version),
      urlDetailRow('Cipher', ssl.cipher),
      urlDetailRow('Error', ssl.error),
    ].join('');
  }
  if (urlSslSection) urlSslSection.style.display = 'block';

  // Threat intelligence
  const rep = r.reputation || {};
  if (urlThreatEl) {
    urlThreatEl.innerHTML = [
      urlDetailRow('Provider', rep.provider),
      urlDetailRow('Reputation', rep.reputation),
      urlDetailRow('Malware', rep.malware),
      urlDetailRow('Phishing', rep.phishing),
      urlDetailRow('Note', rep.note),
    ].join('');
  }
  if (urlThreatSection) urlThreatSection.style.display = 'block';

  // Security findings
  const findings = r.findings || [];
  if (urlFindingsEl) {
    urlFindingsEl.innerHTML = findings.length ? findings.map(function (f) {
      return '<div class="url-finding ' + (f.severity || 'INFO') + '">'
        + '<div class="url-finding-title">[' + escapeHtml(f.severity || 'INFO') + '] ' + escapeHtml(f.title || '') + '</div>'
        + (f.detail ? '<div class="url-finding-detail">' + escapeHtml(f.detail) + '</div>' : '')
        + '</div>';
    }).join('') : '<div class="url-history-meta">No suspicious indicators were detected during this scan.</div>';
  }
  if (urlFindingsSection) urlFindingsSection.style.display = 'block';

  // Recommendation
  if (urlRecEl) {
    urlRecEl.textContent = r.recommendation || '—';
    urlRecEl.classList.remove('danger');
    if (r.classification === 'MALICIOUS' || r.classification === 'SUSPICIOUS') urlRecEl.classList.add('danger');
  }
  if (urlRecSection) urlRecSection.style.display = 'block';

  // Report actions
  if (urlActionsEl) urlActionsEl.style.display = 'flex';
  setUrlButtonsEnabled(true);
  urlReportReady = false;
  if (urlReportBtn) urlReportBtn.textContent = 'GENERATE REPORT';
}

function updateUrlUI(s) {
  if (!s) return;
  try {
    if (s.scan_id) urlScanId = s.scan_id;

    // Stages section visible while running
    if (urlStagesSection) urlStagesSection.style.display = 'block';

    // Build stage rows once
    if (s.stages && s.stages.length && Object.keys(urlStagesMap).length === 0) {
      buildUrlStages(s.stages);
    }

    // Current stage
    if (s.stage_label) { if (urlStageLabel) urlStageLabel.textContent = s.stage_label; }
    if (s.stage && urlStagesMap[s.stage]) {
      updateUrlStageRow(s.stage, s.stage_status || 'running', s.stage_label);
    }
    // Mark prior stages done
    if (s.stages) {
      let seenCurrent = false;
      s.stages.forEach(function (st) {
        if (st.key === s.stage) { seenCurrent = true; return; }
        if (!seenCurrent && urlStagesMap[st.key]) {
          if (st.status === 'pending') updateUrlStageRow(st.key, 'done');
        }
      });
    }

    // Progress
    const pct = Math.max(0, Math.min(100, s.progress || 0));
    if (urlProgressBar) urlProgressBar.style.width = pct + '%';
    if (urlProgressVal) urlProgressVal.textContent = pct + '%';

    // Badge
    const st = (s.status || '').toUpperCase();
    if (st === 'RUNNING') setUrlBadge('SCANNING');
    else if (st === 'COMPLETE') setUrlBadge('DONE');
    else if (st === 'ERROR') setUrlBadge('ERROR', 'offline');
    else setUrlBadge('READY');

    // Completion -> render full result
    if (st === 'COMPLETE' && s.result) {
      renderUrlResult(s.result);
      loadUrlHistory();
      // Voice summary broadcast (for voice-triggered scans)
      if (s.voice_summary && urlLastChatScan !== s.scan_id) {
        urlLastChatScan = s.scan_id;
        addMessage(s.voice_summary, 'zyra');
      }
    }
    // Error
    if (st === 'ERROR') {
      showUrlError(s.error || 'URL analysis failed.');
    }
  } catch (err) {
    console.error('Error updating URL UI:', err);
  }
}

function startUrlScanManual() {
  const url = (urlInput && urlInput.value || '').trim();
  if (!url) { showUrlError('Please enter a valid URL.'); return; }
  clearUrlError();
  resetUrlResultSections();
  if (urlStagesSection) urlStagesSection.style.display = 'block';
  if (urlAnalyzeBtn) { urlAnalyzeBtn.disabled = true; urlAnalyzeBtn.classList.add('scanning'); }
  setUrlBadge('SCANNING');
  if (urlStageLabel) urlStageLabel.textContent = 'INITIALIZING URL ANALYZER...';
  if (urlProgressBar) urlProgressBar.style.width = '0%';
  if (urlProgressVal) urlProgressVal.textContent = '0%';

  fetch('/api/url/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: url, source: 'panel' }),
  }).then(function (res) { return res.json(); }).then(function (data) {
    if (!data.success) {
      showUrlError(data.error || 'URL analysis could not be started.');
      if (urlAnalyzeBtn) { urlAnalyzeBtn.disabled = false; urlAnalyzeBtn.classList.remove('scanning'); }
      return;
    }
    urlScanId = data.scan_id;
    if (urlAnalyzeBtn) { urlAnalyzeBtn.disabled = false; urlAnalyzeBtn.classList.remove('scanning'); }
  }).catch(function (err) {
    showUrlError('Could not reach the ZYRA backend: ' + err);
    if (urlAnalyzeBtn) { urlAnalyzeBtn.disabled = false; urlAnalyzeBtn.classList.remove('scanning'); }
  });
}

function generateUrlReport() {
  if (!urlScanId) return;
  if (urlReportBtn) { urlReportBtn.disabled = true; urlReportBtn.textContent = 'GENERATING REPORT...'; }
  fetch('/api/url/report/' + urlScanId + '?format=txt', { method: 'GET' })
    .then(function (res) { return res.text(); })
    .then(function (text) {
      urlReportReady = true;
      if (urlReportBtn) { urlReportBtn.disabled = false; urlReportBtn.textContent = 'REPORT READY'; }
      if (urlDownloadBtn) urlDownloadBtn.disabled = false;
      // Brief confirmation in chat
      addMessage('URL analysis report generated. Click DOWNLOAD REPORT to save the PDF.', 'zyra');
    }).catch(function (err) {
      if (urlReportBtn) { urlReportBtn.disabled = false; urlReportBtn.textContent = 'GENERATE REPORT'; }
      showUrlError('Report generation failed: ' + err);
    });
}

function downloadUrlReport() {
  if (!urlScanId) return;
  window.open('/api/url/report/' + urlScanId + '?format=pdf', '_blank');
}

function loadUrlHistory() {
  fetch('/api/url/history').then(function (res) { return res.json(); }).then(function (data) {
    if (!data.success || !data.data || !data.data.length) {
      if (urlHistoryEl) urlHistoryEl.innerHTML = '<div class="url-history-meta">No recent scans.</div>';
      return;
    }
    if (urlHistoryEmpty) urlHistoryEmpty.remove();
    if (urlHistoryEl) {
      urlHistoryEl.innerHTML = data.data.map(function (h) {
        const cls = (h.classification === 'MALICIOUS') ? 'danger'
          : (h.classification === 'SUSPICIOUS') ? 'suspicious' : 'safe';
        const scoreColor = (h.score >= 70) ? '#00ff88' : (h.score >= 40 ? '#ffaa00' : '#ff3333');
        return '<div class="url-history-item" data-scan-id="' + escapeHtml(h.scan_id) + '">'
          + '<span class="url-history-domain">' + escapeHtml(h.domain || h.url || '—') + '</span>'
          + '<span class="url-history-meta">Score: <span style="color:' + scoreColor + ';font-weight:700">' + h.score + '</span> &middot; ' + escapeHtml(h.classification_label || h.classification || '') + ' &middot; ' + escapeHtml(h.timestamp_display || '') + '</span>'
          + '</div>';
      }).join('');
      // Click to reopen
      urlHistoryEl.querySelectorAll('.url-history-item').forEach(function (item) {
        item.addEventListener('click', function () {
          const sid = item.getAttribute('data-scan-id');
          if (sid) reopenUrlScan(sid);
        });
      });
    }
  }).catch(function () { /* history is best-effort */ });
}

function reopenUrlScan(scanId) {
  fetch('/api/url/result/' + scanId).then(function (res) { return res.json(); }).then(function (data) {
    if (data.success && data.data) {
      clearUrlError();
      resetUrlResultSections();
      urlScanId = scanId;
      setUrlBadge('DONE');
      renderUrlResult(data.data);
      openUrlPanel();
    }
  }).catch(function () { /* ignore */ });
}

// Event wiring
if (urlAnalyzeBtn) urlAnalyzeBtn.addEventListener('click', startUrlScanManual);
if (urlInput) {
  urlInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); startUrlScanManual(); }
  });
}
if (urlReportBtn) urlReportBtn.addEventListener('click', generateUrlReport);
if (urlDownloadBtn) urlDownloadBtn.addEventListener('click', downloadUrlReport);

// Load history on init
loadUrlHistory();
