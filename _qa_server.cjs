// Tiny static server used only for QA: serves the dashboard with the same
// instrumentation the browser harness needs, on a real localhost origin.
const http = require('http');
const fs = require('fs');

const target = 'desktop-dashboard/index.html';
const html = fs.readFileSync(target, 'utf8');
const served = html.replace(
  '    renderer.render(scene, camera);',
  '    window.__core = { scene: scene, renderer: renderer, camera: camera };\n    renderer.render(scene, camera);'
);
if (served === html) {
  console.error('instrumentation anchor missing');
  process.exit(1);
}

http.createServer((req, res) => {
  if (req.url === '/' || req.url === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(served);
    return;
  }
  res.writeHead(503, { 'Content-Type': 'application/json' });
  res.end('{}');
}).listen(8099, '127.0.0.1', () => console.log('qa server on http://127.0.0.1:8099'));
