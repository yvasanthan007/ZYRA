// Diagnostic: reproduce the 'spawn UNKNOWN' failure electron-builder hits.
const { execFile } = require('child_process');

function test(label, file, args, options, cb) {
  execFile(file, args, options, (err, so, se) => {
    if (err) {
      console.log(label.padEnd(46), 'ERR', err.code || err.message);
    } else {
      console.log(label.padEnd(46), 'OK', String(so).trim().slice(0, 40));
    }
    if (cb) cb();
  });
}

const cmd = process.env.COMSPEC || 'C:\\Windows\\System32\\cmd.exe';

test('cmd + RunAsInvoker env', cmd, ['/c', 'echo hello'], { env: { __COMPAT_LAYER: 'RunAsInvoker' } }, () => {
  test('cmd + inherited env', cmd, ['/c', 'echo hello'], {}, () => {
    console.log('PROBE DONE');
  });
});
