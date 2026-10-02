/**
 * Headless verification harness for the ZYRA Electron shell.
 * Boots the real main process offscreen: loads the existing dashboard,
 * injects the title bar, exercises window controls + desktop IPC, and
 * prints a machine-readable JSON report. No UI is redesigned.
 *
 * Usage: node electron/verify.js [--url http://127.0.0.1:8080]
 */
'use strict';

const { spawn } = require('child_process');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const ELECTRON_CLI = path.join(ROOT, 'node_modules', 'electron', 'cli.js');

function argValue(name, fallback) {
  const idx = process.argv.indexOf(name);
  if (idx >= 0 && process.argv[idx + 1]) return process.argv[idx + 1];
  return fallback;
}

async function main() {
  const url = argValue('--url', process.env.ZYRA_DEV_URL || 'http://127.0.0.1:8080');
  const checks = [];
  const record = (name, ok, detail) => {
    checks.push({ name, ok: !!ok, detail: detail || '' });
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
  };

  // 1) Backend reachable (existing FastAPI contract preserved).
  try {
    const res = await fetch(`${url}/api/health`);
    const body = await res.json();
    record('backend /api/health reachable', res.ok && body && body.status === 'ok', JSON.stringify(body));
  } catch (err) {
    record('backend /api/health reachable', false, String((err && err.message) || err));
  }

  // 2) Existing dashboard HTML still served unmodified at /.
  try {
    const res = await fetch(`${url}/`);
    const html = await res.text();
    const ok = res.ok && html.includes('id="dashboard-overlay"') && html.includes('id="top-bar"');
    record('dashboard overlay + top-bar present', ok, `bytes=${html.length}`);
  } catch (err) {
    record('dashboard overlay + top-bar present', false, String((err && err.message) || err));
  }

  // 3) Existing REST surface intact.
  for (const endpoint of ['/api/commands', '/api/nmap/operations', '/api/system/metrics']) {
    try {
      const res = await fetch(url + endpoint);
      record(`GET ${endpoint} -> ${res.status}`, res.ok, `status=${res.status}`);
    } catch (err) {
      record(`GET ${endpoint}`, false, String((err && err.message) || err));
    }
  }

  // 4) Boot the real Electron shell offscreen and verify title bar injection.
  const child = spawn(process.execPath, [ELECTRON_CLI, path.join(__dirname, 'verify-helper.js')], {
    env: { ...process.env, ZYRA_VERIFY_URL: url, ELECTRON_ENABLE_LOGGING: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stdout = '';
  let stderr = '';
  child.stdout.on('data', (d) => { stdout += d; });
  child.stderr.on('data', (d) => { stderr += d; });
  const exitCode = await new Promise((resolve) => {
    const timer = setTimeout(() => {
      try { child.kill(); } catch (_) { /* ignore */ }
      resolve(99);
    }, 60000);
    child.on('close', (code) => { clearTimeout(timer); resolve(code); });
  });

  let helperReport = null;
  const jsonStart = stdout.indexOf('{');
  const jsonEnd = stdout.lastIndexOf('}');
  if (jsonStart >= 0 && jsonEnd > jsonStart) {
    try {
      helperReport = JSON.parse(stdout.slice(jsonStart, jsonEnd + 1));
    } catch (_) { /* fall through */ }
  }
  if (helperReport && Array.isArray(helperReport.checks)) {
    for (const c of helperReport.checks) record(`electron: ${c.name}`, c.ok, c.detail);
  } else {
    record('electron offscreen boot', exitCode === 0, `exit=${exitCode} stderr=${stderr.slice(-400)}`);
  }

  const failed = checks.filter((c) => !c.ok);
  console.log(`\n${checks.length - failed.length}/${checks.length} checks passed.`);
  if (failed.length) {
    console.log('Failures:');
    for (const f of failed) console.log(` - ${f.name}: ${f.detail}`);
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error('verify failed:', err);
  process.exitCode = 1;
});
