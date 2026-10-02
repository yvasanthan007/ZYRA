/**
 * Injects the custom ZYRA title bar into the EXISTING dashboard page.
 * No dashboard source files are modified — CSS/JS are applied at runtime via
 * webContents (works for both dev server and packaged backend URLs).
 */
'use strict';

const fs = require('fs');
const path = require('path');

function readAsset(name) {
  return fs.readFileSync(path.join(__dirname, name), 'utf-8');
}

function injectTitlebar(webContents) {
  const css = readAsset('titlebar.css');
  const js = readAsset('titlebar.js');
  webContents.insertCSS(css).catch(() => {});
  webContents.executeJavaScript(js, true).catch(() => {});
}

function setupTitlebarInjection(browserWindow) {
  if (!browserWindow || !browserWindow.webContents) return;
  browserWindow.webContents.on('did-finish-load', () => {
    injectTitlebar(browserWindow.webContents);
  });
  // SPA-style re-renders / WS-driven DOM resets: re-assert presence cheaply.
  browserWindow.webContents.on('did-frame-finish-load', (_event, isMainFrame) => {
    if (isMainFrame) injectTitlebar(browserWindow.webContents);
  });
}

module.exports = { injectTitlebar, setupTitlebarInjection };
