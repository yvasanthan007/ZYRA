export default async function run(page, ui) {
  const result = {};

  // Open panel + start scan.
  await page.evaluate(() => document.getElementById('btn-toggle-url').click());
  await page.waitForTimeout(400);

  // Check WS connection state.
  result.wsState = await page.evaluate(() => {
    if (typeof ws === 'undefined' || !ws) return 'no-ws';
    return ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'][ws.readyState];
  });

  // Track WS messages received.
  await page.evaluate(() => {
    window.__urlMsgs = [];
    const orig = ws.onmessage;
    ws.onmessage = function (ev) {
      try {
        const d = JSON.parse(ev.data);
        if (d.type && d.type.indexOf('url') !== -1) window.__urlMsgs.push(d.type + ':' + (d.data && d.data.status));
      } catch (e) { }
      if (orig) orig.call(ws, ev);
    };
  });

  // Start scan.
  await page.evaluate(() => { const i = document.getElementById('url-input'); i.value = 'https://example.com'; });
  const scanId = await page.evaluate(async () => {
    const r = await fetch('/api/url/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: 'https://example.com', source: 'panel' }) });
    const j = await r.json();
    return j;
  });
  result.scanStart = scanId;

  // Poll the REST status endpoint from inside the page and drive the UI directly.
  let final = null;
  for (let i = 0; i < 18; i++) {
    await page.waitForTimeout(4000);
    const poll = await page.evaluate(async (sid) => {
      try {
        const r = await fetch('/api/url/status/' + sid);
        const j = await r.json();
        return j.data;
      } catch (e) { return null; }
    }, scanId.scan_id);
    if (poll) {
      // Drive the UI with the polled state (fallback if WS doesn't deliver).
      await page.evaluate((st) => { if (typeof updateUrlUI === 'function') updateUrlUI(st); }, poll);
      if (poll.status === 'COMPLETE' || poll.status === 'ERROR') { final = poll; break; }
    }
  }
  result.urlWsMsgs = await page.evaluate(() => window.__urlMsgs);
  result.finalStatus = final ? final.status : 'TIMEOUT';

  if (final && final.status === 'COMPLETE') {
    result.score = await page.evaluate(() => document.getElementById('url-score').textContent.trim());
    result.riskLabel = await page.evaluate(() => document.getElementById('url-risk-label').textContent.trim());
    result.classLabel = await page.evaluate(() => document.getElementById('url-class-label').textContent.trim());
    result.urlDetailRows = await page.evaluate(() => document.querySelectorAll('#url-details .url-detail-row').length);
    result.sslDetailRows = await page.evaluate(() => document.querySelectorAll('#url-ssl .url-detail-row').length);
    result.threatDetailRows = await page.evaluate(() => document.querySelectorAll('#url-threat .url-detail-row').length);
    result.findingsCount = await page.evaluate(() => document.querySelectorAll('#url-findings .url-finding').length);
    result.checksCount = await page.evaluate(() => document.querySelectorAll('#url-checks .url-check').length);
    result.historyItems = await page.evaluate(() => document.querySelectorAll('#url-history .url-history-item').length);
    result.reportBtnDisabled = await page.evaluate(() => document.getElementById('url-report-btn').disabled);
    // Generate report.
    await page.evaluate(() => document.getElementById('url-report-btn').click());
    await page.waitForTimeout(2000);
    result.reportBtnText = await page.evaluate(() => document.getElementById('url-report-btn').textContent.trim());
    result.downloadBtnDisabled = await page.evaluate(() => document.getElementById('url-download-btn').disabled);
  }
  return result;
}
