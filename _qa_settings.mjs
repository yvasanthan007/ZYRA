export default async function run(page, ui) {
  const out = {};
  const snap = await ui.snapshot();
  const settingsRef = snap.match(/@(\S+) button "Open ZYRA Settings"/)?.[1];
  await ui.click(settingsRef);
  await page.waitForTimeout(400);
  out.modalVisible = await page.evaluate(() => document.getElementById('zyra-settings-overlay').classList.contains('visible'));

  // Theme -> Light
  await page.selectOption('#zs-theme', 'light');
  await page.waitForTimeout(200);
  out.lightApplied = await page.evaluate(() => document.body.classList.contains('zyra-light'));

  // Font size -> Large
  await page.selectOption('#zs-fontsize', '110');
  await page.waitForTimeout(150);
  out.zoom = await page.evaluate(() => document.body.style.zoom);

  // Accent: 3rd swatch
  out.accentPicked = await page.evaluate(() => {
    const sw = document.querySelectorAll('#zs-accent-swatches .zs-swatch');
    sw[2].click(); return sw[2].dataset.color;
  });
  await page.waitForTimeout(150);
  out.accentVar = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--zyra-accent').trim());

  // Voice toggle off then on; volume 50
  await page.evaluate(() => document.getElementById('zs-voice-toggle').click());
  await page.waitForTimeout(100);
  out.voiceOff = await page.evaluate(() => !document.getElementById('zs-voice-toggle').classList.contains('on'));
  await page.evaluate(() => document.getElementById('zs-voice-toggle').click());
  await page.waitForTimeout(100);
  out.voiceOn = await page.evaluate(() => document.getElementById('zs-voice-toggle').classList.contains('on'));
  await page.evaluate(() => { const el = document.getElementById('zs-voice-volume'); el.value = '50'; el.dispatchEvent(new Event('input', {bubbles:true})); });
  await page.waitForTimeout(100);
  out.voiceVol = await page.evaluate(() => document.getElementById('zs-voice-volume-val').textContent);

  // Wake word
  await page.evaluate(() => { const el = document.getElementById('zs-wakeword'); el.value = 'Hey ZYRA'; el.dispatchEvent(new Event('change', {bubbles:true})); });
  await page.waitForTimeout(100);
  out.wakeWord = await page.evaluate(() => JSON.parse(localStorage.getItem('zyra_settings_v1')||'{}').wakeWord);

  const persisted = await page.evaluate(() => JSON.parse(localStorage.getItem('zyra_settings_v1')||'{}'));
  out.persisted = { theme: persisted.theme, fontSize: persisted.fontSize, accent: persisted.accent, voiceEnabled: persisted.voiceEnabled, voiceVolume: persisted.voiceVolume, wakeWord: persisted.wakeWord, saveHistory: persisted.saveHistory };

  // Open chat sidebar
  await page.evaluate(() => document.getElementById('zs-sidebar-open').click());
  await page.waitForTimeout(250);
  out.sidebarOpen = await page.evaluate(() => document.getElementById('zyra-chat-sidebar').classList.contains('open'));

  // Send a chat message via the real input + button (records into history)
  await page.evaluate(() => {
    const inp = document.getElementById('chat-input');
    inp.value = 'Hello ZYRA, test message';
    document.getElementById('chat-send').click();
  });
  await page.waitForTimeout(600);
  out.sessionsCount = await page.evaluate(() => JSON.parse(localStorage.getItem('zyra_chat_sessions_v1')||'[]').length);
  out.firstSessionTitle = await page.evaluate(() => (JSON.parse(localStorage.getItem('zyra_chat_sessions_v1')||'[]')[0]||{}).title);

  // Clear chat history
  await page.evaluate(() => document.getElementById('zs-clear-history').click());
  await page.waitForTimeout(150);
  out.historyCleared = await page.evaluate(() => JSON.parse(localStorage.getItem('zyra_chat_sessions_v1')||'[]').length === 0);

  // Close modal
  await page.evaluate(() => document.getElementById('zyra-settings-close').click());
  await page.waitForTimeout(200);
  out.modalClosed = await page.evaluate(() => !document.getElementById('zyra-settings-overlay').classList.contains('visible'));

  return out;
}
