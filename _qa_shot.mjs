export default async function run(page, ui) {
  const snap = await ui.snapshot();
  const settingsRef = snap.match(/@(\S+) button "Open ZYRA Settings"/)?.[1];
  await ui.click(settingsRef);
  await page.waitForTimeout(500);
  return { opened: true };
}
