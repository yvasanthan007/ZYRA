const fs = require('fs');
const path = '_theme_qa_colors.mjs';
const lines = fs.readFileSync(path, 'utf8').split(/\r?\n/);
lines[23] = '    try { localStorage.clear(); } catch (err) { /* storage unavailable */ }';
fs.writeFileSync(path, lines.join('\n'));
console.log(lines.slice(21, 27).join('\n'));
