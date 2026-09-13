import fs from 'node:fs';

export default async function run(page) {
  const rx = page.route ? 'playwright' : 'other';
  const requests = [];
  page.on('request', r => requests.push(['request', r.resourceType(), r.url()]));
  page.on('response', r => requests.push(['response', r.status(), r.url().slice(0, 60)]));
  await page.route('http://zyra-probe.test/**', route => {
    if (route.request().resourceType() === 'document') {
      const body = fs.readFileSync('C:/Users/Rakshanaa/Project/ZYRA/desktop-dashboard/index.html', 'utf8');
      return route.fulfill({ status: 200, contentType: 'text/html', body });
    }
    return route.fulfill({ status: 503, body: '{}' });
  });
  await page.goto('http://zyra-probe.test/').catch(() => {});
  await page.waitForTimeout(3000);
  await page.waitForTimeout(1500);
  const state = await page.evaluate(() => ({
    three: String(window.THREE),
    start: String(window.__threeStart),
    loaded: String(window.__threeLoaded),
    boot: String(window.__boot),
    qa: String(window.__themeQA),
    scripts: Array.from(document.scripts).map(s => s.textContent.length)
  }));
  return { rx, state, events: requests.slice(0, 20) };
}
