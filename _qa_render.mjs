export default async function run(page, ui) {
  // Open panel, start scan, poll, and directly call renderUrlResult with the
  // result payload to isolate whether updateUrlUI or renderUrlResult is broken.
  await page.evaluate(() => document.getElementById('btn-toggle-url').click());
  await page.waitForTimeout(400);

  const scanStart = await page.evaluate(async () => {
    const r = await fetch('/api/url/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: 'https://example.com', source: 'panel' }) });
    return await r.json();
  });
  if (!scanStart.success) return { rejected: scanStart };

  // Poll until complete.
  let final = null;
  for (let i = 0; i < 18; i++) {
    await page.waitForTimeout(4000);
    const poll = await page.evaluate(async (sid) => {
      try { const r = await fetch('/api/url/status/' + sid); const j = await r.json(); return j.data; } catch (e) { return null; }
    }, scanStart.scan_id);
    if (poll && (poll.status === 'COMPLETE' || poll.status === 'ERROR')) { final = poll; break; }
  }
  if (!final) return { finalStatus: 'TIMEOUT' };

  // Directly call renderUrlResult with the result payload.
  const renderOutcome = await page.evaluate((resPayload) => {
    try {
      if (typeof renderUrlResult !== 'function') return { error: 'renderUrlResult not defined' };
      renderUrlResult(resPayload);
      return {
        ok: true,
        scoreText: document.getElementById('url-score').textContent.trim(),
        resultDisplay: document.getElementById('url-result-section').style.display,
        detailsDisplay: document.getElementById('url-details-section').style.display,
        detailRows: document.querySelectorAll('#url-details .url-detail-row').length,
        sslRows: document.querySelectorAll('#url-ssl .url-detail-row').length,
        threatRows: document.querySelectorAll('#url-threat .url-detail-row').length,
        findingsCount: document.querySelectorAll('#url-findings .url-finding').length,
        checksCount: document.querySelectorAll('#url-checks .url-check').length,
        recText: (document.getElementById('url-recommendation').textContent || '').slice(0, 60),
        actionsDisplay: document.getElementById('url-actions').style.display,
        reportBtnDisabled: document.getElementById('url-report-btn').disabled,
      };
    } catch (e) { return { error: e.message }; }
  }, final.result);

  return { finalStatus: final.status, renderOutcome };
}
