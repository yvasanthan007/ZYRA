const fs = require('fs');
// three.js r128, exactly what the CDN tag referenced, kept local so it works offline.
const three = fs.readFileSync('desktop-dashboard/vendor/three.r128.min.js', 'utf8');
const tag = '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>';
const files = ['desktop-dashboard/index.html', 'desktop-dashboard/dashboard.html', 'index.html'];
for (const file of files) {
  if (!fs.existsSync(file)) continue;
  let html = fs.readFileSync(file, 'utf8');
  if (!html.includes(tag)) { console.log(file, 'no tag'); continue; }
  html = html.replace(tag, '<script>\n' + three + '\n</script>');
  fs.writeFileSync(file, html);
  console.log(file, 'inlined three.js, bytes =', html.length);
}
