export default async function run(page, ui) {
  const out = {};

  // 1) Structural verification.
  out.topButtons = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.top-btn .btn-text')).map(e => e.textContent.trim()));
  out.hasSystemMonitorCard = !!(await page.$('#system-monitor-card'));
  out.hasNmapCard = !!(await page.$('#nmap-scanner-card'));
  out.hasUrlCard = !!(await page.$('#url-analyzer-card'));

  // 2) Trigger via chat: "Analyze https://example.com" — real user flow.
  const snap = await ui.snapshot();
  const inputRef = snap.match(/@(e\d+) textbox.*Message ZYRA/i)?.[1] || snap.match(/@(e\d+) textbox/)?.[1];
  const sendRef = snap.match(/@(e\d+) button "➤"/)?.[1];

  if (inputRef) await ui.fill(inputRef, 'Analyze https://example.com');
  if (sendRef) await ui.click(sendRef);

  // 3) Wait for the panel to open (chat intent -> show_url_analyzer broadcast).
  try {
    await page.waitForFunction(() => document.getElementById('url-analyzer-card').classList.contains('visible'), { timeout: 15000 });
    out.panelOpenedFromChat = true;
  } catch (e) { out.panelOpenedFromChat = false; }

  if (out.panelOpenedFromChat) {
    out.urlInputAutoFilled = await page.evaluate(() => document.getElementById('url-input').value);
  }

  // 4) Wait for WS-driven scan completion (result section + score populated).
  let completed = false;
  try {
    await page.waitForFunction(() => {
      const s = document.getElementById('url-result-section');
      return s && s.style.display !== 'none' && document.getElementById('url-score').textContent.trim() !== '--';
    }, { timeout: 80000 });
    completed = true;
  } catch (e) { completed = false; }
  out.completed = completed;

  if (completed) {
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
    out.recommendation = await page.evaluate(() => (document.getElementById('url-recommendation').textContent || '').slice(0, 80));

    // 5) Generate report via button.
    const snap2 = await ui.snapshot();
    const reportRef = snap2.match(/@(e\d+) button "GENERATE REPORT"/)?.[1];
    if (reportRef) await ui.click(reportRef);
    await page.waitForTimeout(2500);
    out.reportBtnText = await page.evaluate(() => document.getElementById('url-report-btn').textContent.trim());
    out.downloadBtnDisabled = await page.evaluate(() => document.getElementById('url-download-btn').disabled);
  } else {
    out.stageLabel = await page.evaluate(() => { const el = document.getElementById('url-stage-label'); return el ? el.textContent.trim() : null; });
    out.badge = await page.evaluate(() => { const el = document.getElementById('url-badge'); return el ? el.textContent.trim() : null; });
  }
  return out;
}
