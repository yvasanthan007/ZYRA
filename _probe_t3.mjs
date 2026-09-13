import fs from 'node:fs';

export default async function run(page) {
  const html = fs.readFileSync('C:/Users/Rakshanaa/Project/ZYRA/desktop-dashboard/index.html', 'utf8');
  await page.route('http://zyra-t3.test/**', route => {
    if (route.request().resourceType() === 'document') {
      return route.fulfill({ status: 200, contentType: 'text/html', body: html });
    }
    return route.fulfill({ status: 503, body: '{}' });
  });
  await page.goto('http://zyra-t3.test/').catch(() => {});
  await page.waitForTimeout(4000);
  return page.evaluate(() => ({
    three: String(typeof window.THREE),
    torus: String(typeof (window.THREE && window.THREE.TorusGeometry)),
    canvas: document.querySelectorAll('canvas').length,
    scripts: document.scripts.length
  }));
}
