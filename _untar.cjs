// Minimal tar reader: extracts one file out of a .tgz (gzip) archive.
const fs = require('fs');
const zlib = require('zlib');
const [archive, target, outPath] = process.argv.slice(2);
const buffer = zlib.gunzipSync(fs.readFileSync(archive));
let offset = 0;
while (offset + 512 <= buffer.length) {
  const header = buffer.subarray(offset, offset + 512);
  const name = header.subarray(0, 100).toString('utf8').replace(/\0.*$/, '');
  if (!name) break;
  const size = parseInt(header.subarray(124, 136).toString('utf8').replace(/\0.*$/, '').trim(), 8) || 0;
  const start = offset + 512;
  if (name === target) {
    fs.writeFileSync(outPath, buffer.subarray(start, start + size));
    console.log('extracted', name, size, 'bytes');
    process.exit(0);
  }
  offset = start + Math.ceil(size / 512) * 512;
}
console.error('not found:', target);
process.exit(1);
