import fs from 'node:fs';

export default async function run(page) {
  const html = fs.readFileSync('C:/Users/Rakshanaa/Project/ZYRA/_theme_qa_served.html', 'utf8');
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  await page.goto('file:///C:/Users/Rakshanaa/Project/ZYRA/_theme_qa_served.html').catch(() => {});
  const results = [];
  for (const [i, code] of scripts.entries()) {
    try {
      await page.evaluate(src => { window.__evalProbe = (0, eval)(src); return true; }, code);
      results.push({ i, ok: true });
    } catch (e) {
      results.push({ i, ok: false, error: e.message, len: code.length, head: code.slice(0, 50) });
    }
  }
  return { results, state: await page.evaluate(() => document.readyState) };
}
