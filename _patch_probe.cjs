const fs = require('fs');
const path = '_theme_qa_colors.mjs';
const lines = fs.readFileSync(path, 'utf8').split(/\r?\n/);
lines[33] = "    const probe = await page.evaluate(() => ({ scripts: Array.from(document.scripts).map(x => x.textContent.length), htmlBytes: document.documentElement.outerHTML.length })).catch(() => null);";
lines[34] = "    console.log('[probe]', JSON.stringify(probe));";
fs.writeFileSync(path, lines.join('\n'));
console.log(lines.slice(31, 37).join('\n'));
