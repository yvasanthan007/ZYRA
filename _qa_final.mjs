export default async function run(page, ui) {
  const out = {};

  // 1) Verify all three top-right buttons in order.
  out.topButtons = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.top-btn .btn-text')).map(e => e.textContent.trim()));

  // 2) Verify System Monitor + Nmap cards still present (not disturbed).
  out.hasSystemMonitorCard = !!(await page.$('#system-monitor-card'));
  out.hasNmapCard = !!(await page.$('#nmap-scanner-card'));
  out.hasUrlCard = !!(await page.$('#url-analyzer-card'));
  out.hasChatInput = !!(await page.$('#chat-input'));
  out.hasChatSend = !!(await page.$('#chat-send'));

  // 3) Open URL panel via button, verify header.
  await page.evaluate(() => document.getElementById('btn-toggle-url').click());
  await page.waitForTimeout(450);
  out.panelVisible = await page.evaluate(() => document.getElementById('url-analyzer-card').classList.contains('visible'));
  out.panelTitle = await page.evaluate(() => (document.querySelector('#url-analyzer-card .url-title') || {}).textContent);
  out.panelSubtitle = await page.evaluate(() => (document.querySelector('#url-analyzer-card .url-subtitle') || {}).textContent);
  out.hasUrlInput = !!(await page.$('#url-input'));
  out.analyzeBtnText = await page.evaluate(() => document.getElementById('url-analyze-btn').textContent.trim());

  // 4) Start a scan via the REST API (reliable), then poll status and drive
  //    updateUrlUI directly to prove the render path works end-to-end.
  const start = await page.evaluate(async () => {
    const r = await fetch('/api/url/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: 'https://example.com', source: 'panel' }) });
    return await r.json();
  });
  out.scanStart = start;
  if (!start.success) return out;

  let final = null;
  for (let i = 0; i < 25; i++) {
    await page.waitForTimeout(3000);
    const st = await page.evaluate(async (sid) => {
      try { const r = await fetch('/api/url/status/' + sid); const j = await r.json(); return j.data; } catch (e) { return null; }
    }, start.scan_id);
    if (st) {
      await page.evaluate((s) => { if (typeof updateUrlUI === 'function') updateUrlUI(s); }, st);
      if (st.status === 'COMPLETE' || st.status === 'ERROR') { final = st; break; }
    }
  }
  out.finalStatus = final ? final.status : 'TIMEOUT';

  if (final && final.status === 'COMPLETE' && final.result) {
    out.score = await page.evaluate(() => document.getElementById('url-score').textContent.trim());
    out.riskLabel = await page.evaluate(() => document.getElementById('url-risk-label').textContent.trim());
    out.classLabel = await page.evaluate(() => document.getElementById('url-class-label').textContent.trim());
    out.badge = await page.evaluate(() => document.getElementById('url-badge').textContent.trim());
    out.urlDetailRows = await page.evaluate(() => document.querySelectorAll('#url-details .url-detail-row').length);
    out.sslDetailRows = await page.evaluate(() => document.querySelectorAll('#url-ssl .url-detail-row').length);
    out.threatDetailRows = await page.evaluate(() => document.querySelectorAll('#url-threat .url-detail-row').length);
    out.findingsCount = await page.evaluate(() => document.querySelectorAll('#url-findings .url-finding').length);
    out.checksCount = await page.evaluate(() => document.querySelectorAll('#url-checks .url-check').length);
    out.historyItems = await page.evaluate(() => document.querySelectorAll('#url-history .url-history-item').length);
    out.recommendation = await page.evaluate(() => (document.getElementById('url-recommendation').textContent || '').slice(0, 70));
    out.reportBtnDisabled = await page.evaluate(() => document.getElementById('url-report-btn').disabled);
    out.downloadBtnDisabled = await page.evaluate(() => document.getElementById('url-download-btn').disabled);

    // 5) Generate report -> REPORT READY.
    await page.evaluate(() => document.getElementById('url-report-btn').click());
    await page.waitForTimeout(2500);
    out.reportBtnText = await page.evaluate(() => document.getElementById('url-report-btn').textContent.trim());
    out.downloadBtnDisabledAfter = await page.evaluate(() => document.getElementById('url-download-btn').disabled);

    // 6) Verify the PDF endpoint returns a real PDF (from page context).
    out.pdfCheck = await page.evaluate(async (sid) => {
      try {
        const r = await fetch('/api/url/report/' + sid + '?format=pdf');
        const ct = r.headers.get('content-type') || '';
        const cd = r.headers.get('content-disposition') || '';
        const buf = await r.arrayBuffer();
        const head = new Uint8Array(buf.slice(0, 5));
        const sig = String.fromCharCode.apply(null, head);
        return { ok: r.ok, status: r.status, contentType: ct, contentDisposition: cd, bytes: buf.byteLength, signature: sig };
      } catch (e) { return { error: e.message }; }
    }, start.scan_id);
  }
  return out;
}
