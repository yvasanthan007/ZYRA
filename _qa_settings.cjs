// Headless QA for the ZYRA Settings Panel.
// Run: electron _qa_settings.cjs   (server must already be running on 127.0.0.1:8123)
const { app, BrowserWindow } = require('electron');

const URL = 'http://127.0.0.1:8123/';
app.disableHardwareAcceleration();

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    webPreferences: { backgroundThrottling: false, contextIsolation: true, nodeIntegration: false }
  });

  const out = {};
  const pageErrors = [];
  win.webContents.on('console-message', (_e, level, message) => {
    if (level === 'error') pageErrors.push(String(message).slice(0, 180));
  });
  win.webContents.on('render-process-gone', (_e, details) => { out.renderGone = details.reason; });

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const js = (code) => win.webContents.executeJavaScript(code);

  try {
    await win.loadURL(URL);
    await sleep(2500);

    out.hasGear = await js(`!!document.getElementById('zyra-settings-btn')`);

    out.gearOpensOverlay = await js(`(() => { const o = document.getElementById('settings-overlay'); document.getElementById('zyra-settings-btn').click(); return o.classList.contains('visible'); })()`);
    out.navCount = await js(`document.querySelectorAll('.settings-nav-item').length`);
    out.paneCount = await js(`document.querySelectorAll('.settings-pane').length`);
    out.defaultPane = await js(`document.querySelector('.settings-pane.active').getAttribute('data-settings-content')`);
    out.closeBtn = await js(`!!document.getElementById('settings-close')`);

    await js(`document.querySelector('[data-settings-pane="appearance"]').click()`);
    out.appearanceActive = await js(`document.querySelector('.settings-pane.active').getAttribute('data-settings-content')`);

    await js(`document.querySelector('[data-theme-option="light"]').click()`);
    out.themeAfterLight = await js(`document.documentElement.getAttribute('data-theme')`);

    await js(`document.getElementById('setting-compact').click()`);
    out.compactAttr = await js(`document.documentElement.getAttribute('data-compact')`);

    await js(`document.querySelector('[data-theme-option="dark"]').click()`);
    out.themeAfterDark = await js(`document.documentElement.getAttribute('data-theme')`);

    await js(`document.getElementById('setting-scan-toasts').click()`);
    out.toastPrefOff = await js(`window.ZYRASettings.get('scanToasts')`);

    await js(`document.getElementById('settings-close').click()`);
    out.closedByX = await js(`!document.getElementById('settings-overlay').classList.contains('visible')`);

    await js(`document.getElementById('zyra-settings-btn').click()`);
    await js(`document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`);
    await sleep(300);
    out.closedByEsc = await js(`!document.getElementById('settings-overlay').classList.contains('visible')`);

    out.hasMonitorCard = await js(`!!document.getElementById('system-monitor-card')`);
    out.hasNmapCard = await js(`!!document.getElementById('nmap-scanner-card')`);
    out.hasUrlCard = await js(`!!document.getElementById('url-analyzer-card')`);
    out.hasChat = await js(`!!document.getElementById('chat-input')`);
    out.topButtons = await js(`Array.from(document.querySelectorAll('.top-btn .btn-text')).map(e => e.textContent.trim()).join(',')`);

    await js(`document.getElementById('btn-toggle-url').click()`);
    await sleep(500);
    out.urlPanelOpens = await js(`document.getElementById('url-analyzer-card').classList.contains('visible')`);

    await js(`document.getElementById('zyra-settings-btn').click()`);
    await js(`document.querySelector('[data-settings-pane="privacy"]').click()`);
    await js(`document.getElementById('setting-chat-history').click()`);
    await js(`(() => { const m = document.createElement('div'); m.className='msg system'; m.textContent='persist-check'; document.getElementById('chat-messages').appendChild(m); })()`);
    await sleep(600);
    out.historyStored = await js(`!!localStorage.getItem('zyra.chatHistory.v1')`);
    await js(`document.getElementById('setting-clear-chat').click()`);
    await sleep(700);
    out.historyCleared = await js(`localStorage.getItem('zyra.chatHistory.v1') === null && document.getElementById('chat-messages').textContent.indexOf('Chat history cleared.') !== -1`);

    out.settingsSaved = await js(`localStorage.getItem('zyra.settings.v1') !== null`);
    await js(`localStorage.removeItem('zyra.settings.v1'); localStorage.removeItem('zyra.chatHistory.v1')`);
    out.pageErrors = pageErrors;
  } catch (err) {
    out.exception = String(err);
    out.pageErrors = pageErrors;
  }

  console.log('QA_RESULT:' + JSON.stringify(out, null, 2));
  app.exit(0);
});