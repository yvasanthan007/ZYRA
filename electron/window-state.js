'use strict';

const fs = require('fs');
const path = require('path');
const { app } = require('electron');

const STATE_FILE = 'zyra-window-state.json';
const DEFAULTS = { width: 1400, height: 900, maximized: false, x: undefined, y: undefined };

function statePath() {
  try {
    return path.join(app.getPath('userData'), STATE_FILE);
  } catch (_) {
    return path.join(__dirname, STATE_FILE);
  }
}

function loadWindowState() {
  try {
    const raw = fs.readFileSync(statePath(), 'utf-8');
    const parsed = JSON.parse(raw);
    return {
      width: Number(parsed.width) >= 1000 ? Number(parsed.width) : DEFAULTS.width,
      height: Number(parsed.height) >= 650 ? Number(parsed.height) : DEFAULTS.height,
      x: Number.isFinite(parsed.x) ? parsed.x : undefined,
      y: Number.isFinite(parsed.y) ? parsed.y : undefined,
      maximized: !!parsed.maximized,
    };
  } catch (_) {
    return { ...DEFAULTS };
  }
}

function saveWindowState(win) {
  if (!win || win.isDestroyed()) return;
  try {
    const maximized = win.isMaximized();
    const bounds = win.getBounds();
    const state = {
      width: Math.max(1000, bounds.width || DEFAULTS.width),
      height: Math.max(650, bounds.height || DEFAULTS.height),
      x: maximized ? undefined : bounds.x,
      y: maximized ? undefined : bounds.y,
      maximized,
    };
    fs.mkdirSync(path.dirname(statePath()), { recursive: true });
    fs.writeFileSync(statePath(), JSON.stringify(state, null, 2), 'utf-8');
  } catch (_) { /* best effort only */ }
}

module.exports = { loadWindowState, saveWindowState };
