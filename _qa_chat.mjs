export default async function run(page, ui) {
  const out = {};

  // Check if WS is connected by reading the chat flow.
  // Send a simple chat message and wait for a ZYRA response — this proves WS works.
  const snap = await ui.snapshot();
  const inputRef = snap.match(/@(e\d+) textbox.*Message ZYRA/i)?.[1] || snap.match(/@(e\d+) textbox/)?.[1];
  const sendRef = snap.match(/@(e\d+) button "➤"/)?.[1] || snap.match(/@(e\d+) button "Send"/)?.[1];

  if (inputRef) await ui.fill(inputRef, 'Analyze https://example.com');
  if (sendRef) await ui.click(sendRef);

  // Wait for the URL panel to open (chat intent triggers show_url_analyzer).
  let panelOpened = false;
  try {
    await page.waitForFunction(() => document.getElementById('url-analyzer-card').classList.contains('visible'), { timeout: 15000 });
    panelOpened = true;
  } catch (e) { panelOpened = false; }
  out.panelOpenedFromChat = panelOpened;

  // Check if the URL input got auto-filled with the extracted URL.
  if (panelOpened) {
    out.urlInputValue = await page.evaluate(() => document.getElementById('url-input').value);
  }

  // Wait for the result section to appear (WS-driven scan).
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
    out.classLabel = await page.evaluate(() => document.getElementById('url-class-label').textContent.trim());
    out.badge = await page.evaluate(() => document.getElementById('url-badge').textContent.trim());
    out.findingsCount = await page.evaluate(() => document.querySelectorAll('#url-findings .url-finding').length);
    out.checksCount = await page.evaluate(() => document.querySelectorAll('#url-checks .url-check').length);
    out.historyItems = await page.evaluate(() => document.querySelectorAll('#url-history .url-history-item').length);
  } else {
    // Capture the current stage label + badge to see where it stopped.
    out.stageLabel = await page.evaluate(() => { const el = document.getElementById('url-stage-label'); return el ? el.textContent.trim() : null; });
    out.badge = await page.evaluate(() => { const el = document.getElementById('url-badge'); return el ? el.textContent.trim() : null; });
    out.stagesSectionDisplay = await page.evaluate(() => document.getElementById('url-stages-section').style.display);
  }
  return out;
}
