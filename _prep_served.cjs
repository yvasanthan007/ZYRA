const fs = require('fs');
const root = 'desktop-dashboard';
const src = fs.readFileSync(root + '/index.html', 'utf8');
const TAG = '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>';
let out = src.replace(TAG, '<script src="/three.min.js"></script>');
out = out.replace('</head>', '<script>window.__boot = 1; window.onerror = function (m, f, l) { window.__lastError = m + " @" + f + ":" + l; };</script>\n</head>');
const three = fs.readFileSync('_three.min.js', 'utf8');
out = out.replace('<script src="/three.min.js"></script>', '<script>window.__threeStart = 1;\n' + three + '\nwindow.__threeLoaded = 1;</script>');
out = out.replace('    renderer.render(scene, camera);', '    window.__themeQA = { scene: scene, renderer: renderer, mainGroup: mainGroup, orbitParticleData: orbitParticleData, time: time };\n    renderer.render(scene, camera);');
fs.writeFileSync('_theme_qa_served.html', out);

console.log('has boot:', out.includes('window.__boot = 1'));
console.log('has qa:', out.includes('window.__themeQA ='));
console.log('three inlined:', !out.includes(TAG));
