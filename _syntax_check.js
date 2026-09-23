/**
 * _syntax_check.js — temporary: syntax-check every inline <script> in the
 * dashboard HTML with Node's parser. Temporary tool, safe to delete.
 */
const fs = require('fs');

const html = fs.readFileSync('desktop-dashboard/index.html', 'utf8');
const scriptRe = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;
let match;
let index = 0;
let errors = 0;
while ((match = scriptRe.exec(html)) !== null) {
  index += 1;
  try {
    // Parsing only - the wrapper is never executed.
    new Function(match[1]);
  } catch (err) {
    errors += 1;
    console.log(`SCRIPT #${index} SYNTAX ERROR: ${err.message}`);
  }
}
console.log(`checked ${index} inline scripts, ${errors} error(s)`);
