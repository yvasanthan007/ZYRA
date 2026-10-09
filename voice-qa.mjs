export default async function run(page, ui) {
  const initialSnapshot = await ui.snapshot();
  await page.locator('#chat-input').fill('QA probe');
  await page.locator('#chat-send').click();
  await page.waitForTimeout(400);
  const transcriptShown = (await page.locator('#chat-messages').innerText()).includes('QA probe');
  await page.locator('#voice-toggle').click();
  await page.waitForFunction(() => document.querySelector('#voice-state-label')?.textContent === 'Listening...');
  const activeButton = await page.locator('#voice-toggle').innerText();
  await page.locator('#voice-toggle').click();
  await page.waitForFunction(() => document.querySelector('#voice-state-label')?.textContent === 'Voice ready');
  return { hasVoiceAndSend: initialSnapshot.includes('Start Voice') && initialSnapshot.includes('Send message'), transcriptShown, activeButton, stoppedLabel: await page.locator('#voice-state-label').innerText(), finalButton: await page.locator('#voice-toggle').innerText() };
}
