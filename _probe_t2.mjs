import fs from 'node:fs';

export default async function run(page) {
  const html = fs.readFileSync('C:/Users/Rakshanaa/Project/ZYRA/desktop-dashboard/index.html', 'utf8');
  await page.route('http://zyra-t2.test/**', route => {
    if (route.request().resourceType() === 'document') {
      return route.fulfill({ status: 200, contentType: 'text/html', body: html });
    }
    return route.fulfill({ status: 503, body: '{}' });
  });
  await page.addInitScript(() => {
    window.__initScriptRan = 1;
    setInterval(() => { window.__tickCount = (window.__tickCount || 0) + 1; }, 20);
  });
  await page.goto('http://zyra-t2.test/').catch(() => {});
  await page.waitForTimeout(3000);
  const a = await page.evaluate(() => ({ init: String(window.__initScriptRan), ticks: window.__tickCount || 0, three: String(typeof window.THREE) }));
  await page.waitForTimeout(300);
  const b = await page.evaluate(() => ({ ticks: window.__tickCount || 0 }));
  return { a, b, threeTorus: await page.evaluate(() => String(typeof (window.THREE && window.THREE.TorusGeometry))) };
}
