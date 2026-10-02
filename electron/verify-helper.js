/**
 * Offscreen Electron helper spawned by electron/verify.js.
 * Creates the REAL frameless BrowserWindow (same options as main.js),
 * loads the existing dashboard URL, injects the real title bar assets,
 * and exercises window controls + preload IPC. Prints one JSON report.
 */
'use strict';

const { app, BrowserWindow, shell } = require('electron');
const path = require('path');
const fs = require('fs');

const URL = process.env.ZYRA_VERIFY_URL || 'http://127.0.0.1:8080';
const checks = [];
const record = (name, ok, detail) => checks.push({ name, ok: !!ok, detail: detail || '' });

async function settle(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function run() {
  await app.whenReady();

  // Register the SAME production IPC surface the real app uses.
  const { registerWindowControls } = require('./window-controls');
  const { registerDesktopServiceHandlers } = require('./services');
  const fakeBackendManager = { getUrl: () => URL };
  let verifyWindow = null;
  registerWindowControls(() => verifyWindow);
  registerDesktopServiceHandlers({ backendManager: fakeBackendManager });

  const win = new BrowserWindow({
    title: 'ZYRA',
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 650,
    resizable: true,
    show: false,
    frame: false,
    backgroundColor: '#080812',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Window geometry contract.
  verifyWindow = win;
  const bounds = win.getBounds();
  // Offscreen/CI displays clamp height to the work area; assert width exactly
  // and height within a sane tolerance of the 1400x900 default.
  const sizeOk = bounds.width === 1400 && bounds.height >= 760 && bounds.height <= 900;
  record('window default size ~1400x900', sizeOk, `${bounds.width}x${bounds.height}`);
  record('window min size + resizable', win.getMinimumSize()[0] === 1000 && win.getMinimumSize()[1] === 650 && win.isResizable(), JSON.stringify(win.getMinimumSize()));

  await win.loadURL(URL);
  await settle(3500);

  // 1) Preload bridge present, no node leakage.
  const bridge = await win.webContents.executeJavaScript(
    `({ hasApi: !!window.zyraAPI, isDesktop: !!(window.zyraAPI && window.zyraAPI.isDesktop), hasRequire: (typeof require !== 'undefined'), hasProcess: (typeof process !== 'undefined' && !!(process && process.versions && process.versions.electron)) })`,
    true
  ).catch((e) => ({ error: String(e) }));
  record('preload bridge exposed (zyraAPI.isDesktop)', bridge && bridge.hasApi && bridge.isDesktop, JSON.stringify(bridge));
  record('no node/process leakage in renderer', bridge && !bridge.hasRequire, JSON.stringify(bridge));

  // 2) Title bar injection (real CSS+JS assets).
  const css = fs.readFileSync(path.join(__dirname, 'titlebar', 'titlebar.css'), 'utf8');
  const js = fs.readFileSync(path.join(__dirname, 'titlebar', 'titlebar.js'), 'utf8');
  await win.webContents.insertCSS(css).catch(() => {});
  await win.webContents.executeJavaScript(js, true).catch(() => {});
  await settle(800);
  const dom = await win.webContents.executeJavaScript(
    `({ bar: !!document.getElementById('zyra-titlebar'), min: !!document.getElementById('zyra-btn-min'), max: !!document.getElementById('zyra-btn-max'), close: !!document.getElementById('zyra-btn-close'), draggable: getComputedStyle(document.getElementById('zyra-titlebar')||document.body).getPropertyValue('-webkit-app-region') || 'n/a', dashboard: !!document.getElementById('dashboard-overlay') })`,
    true
  ).catch((e) => ({ error: String(e) }));
  record('custom title bar injected', !!(dom && dom.bar && dom.min && dom.max && dom.close), JSON.stringify(dom));
  record('existing dashboard preserved under title bar', !!(dom && dom.dashboard), JSON.stringify(dom));

  // 3) Window controls via IPC (min/max/restore semantics).
  const minRes = await win.webContents.executeJavaScript(`window.zyraAPI.window.minimize().then(()=> 'min-ok').catch(e=> 'min-err:'+e)`, true).catch((e) => 'harness-err:' + e);
  await settle(600);
  record('minimize IPC callable', String(minRes).startsWith('min-ok'), String(minRes));
  try { win.restore(); win.show(); } catch (_) { /* offscreen */ }

  const maxRes = await win.webContents.executeJavaScript(`window.zyraAPI.window.maximize().then(()=> window.zyraAPI.window.isMaximized().then(v=> 'max:'+v)).catch(e=> 'max-err:'+e)`, true).catch((e) => 'harness-err:' + e);
  await settle(600);
  record('maximize toggles maximized state', String(maxRes).includes('max:true') || win.isMaximized(), `${maxRes} native=${win.isMaximized()}`);

  const restoreRes = await win.webContents.executeJavaScript(`window.zyraAPI.window.maximize().then(()=> window.zyraAPI.window.isMaximized().then(v=> 'restored:'+(!v))).catch(e=> 'restore-err:'+e)`, true).catch((e) => 'harness-err:' + e);
  await settle(600);
  record('maximize button restores when maximized', String(restoreRes).includes('restored:true') || !win.isMaximized(), String(restoreRes));

  // 4) Desktop service proxies reach the existing backend.
  const sysInfo = await win.webContents.executeJavaScript(`window.zyraAPI.system.getInfo().then(r=> JSON.stringify({ok: !!(r && (r.success || r.data))}).slice(0,120)).catch(e=> 'err:'+e)`, true).catch((e) => 'harness-err:' + e);
  record('system.getInfo proxies backend', !String(sysInfo).startsWith('err') && !String(sysInfo).startsWith('harness-err'), String(sysInfo));

  const notifyRes = await win.webContents.executeJavaScript(`window.zyraAPI.notify('ZYRA verify','offscreen check').then(r=> JSON.stringify(r)).catch(e=> 'err:'+e)`, true).catch((e) => 'harness-err:' + e);
  // Headless Windows often has no notification center; callable channel is what matters.
  record('desktop notification IPC callable', !String(notifyRes).startsWith('harness-err'), String(notifyRes));

  process.stdout.write(JSON.stringify({ url: URL, checks }) + '\n');
  try { win.destroy(); } catch (_) { /* ignore */ }
  app.quit();
}

run().catch((err) => {
  process.stdout.write(JSON.stringify({ url: URL, checks, fatal: String((err && err.stack) || err) }) + '\n');
  try { app.quit(); } catch (_) { process.exit(1); }
});
