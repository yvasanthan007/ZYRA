const fs = require('fs');
const html = fs.readFileSync('_theme_qa_served.html', 'utf8');
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]);
console.log('scripts:', scripts.length, scripts.map(s => s.length));
try {
  new Function(scripts[0]);
  console.log('three script: syntax OK');
} catch (e) {
  console.log('three script syntax error:', e.message);
  const idx = (e.stack || '').match(/<anonymous>:(\d+)/);
  console.log('stack hint:', idx && idx[1]);
}
for (const [i, s] of scripts.entries()) {
  try { new Function(s); } catch (e) { console.log('script', i, 'error', e.message); }
}
