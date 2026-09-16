// Probe 3: reproduce electron-builder's exact spawn of the NSIS uninstaller stub.
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const src = path.join(__dirname, 'desktop-dist', 'ZYRA-Setup-1.0.0.exe');
console.log('exists:', fs.existsSync(src));
const buf = fs.readFileSync(src);
console.log('size:', buf.length, '| first bytes:', buf.slice(0, 2).toString('ascii'));

// Run from a temp dir so no artifacts land in desktop-dist
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'zyra-nsis-'));
const copy = path.join(tmp, 'stub.exe');
fs.copyFileSync(src, copy);
console.log('temp copy:', copy);

execFile(copy, [], { env: { __COMPAT_LAYER: 'RunAsInvoker' }, timeout: 120000 },
  (err, so, se) => {
    if (err) {
      console.log('SPAWN RESULT: ERR', err.code, '|', err.message.split('\n')[0]);
    } else {
      console.log('SPAWN RESULT: OK');
    }
    console.log('stdout:', String(so).slice(0, 200));
    console.log('stderr:', String(se).slice(0, 200));
    console.log('files created in temp:', fs.readdirSync(tmp));
    console.log('PROBE3 DONE');
  });