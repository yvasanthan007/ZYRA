'use strict';

const { ipcMain, Notification } = require('electron');
const { getSystemInfo, getNetworkInfo, dnsLookup, nmapScan } = require('./desktop-services');

function withBaseUrl(backendManager) {
  return () => (backendManager ? backendManager.getUrl() : 'http://127.0.0.1:8080');
}

function registerDesktopServiceHandlers({ backendManager }) {
  const getBaseUrl = withBaseUrl(backendManager);

  ipcMain.handle('zyra-backend:url', () => getBaseUrl());

  ipcMain.handle('zyra-system:info', async () => {
    return getSystemInfo(getBaseUrl());
  });

  ipcMain.handle('zyra-system:network', async () => {
    return getNetworkInfo(getBaseUrl());
  });

  ipcMain.handle('zyra-net:dns-lookup', async (_event, args) => {
    const { domain, recordType } = args || {};
    return dnsLookup(getBaseUrl(), domain, recordType);
  });

  ipcMain.handle('zyra-net:nmap-scan', async (_event, payload) => {
    return nmapScan(getBaseUrl(), payload);
  });

  ipcMain.handle('zyra:notify', async (_event, args) => {
    const { title, body } = args || {};
    try {
      const note = new Notification({
        title: String(title || 'ZYRA'),
        body: String(body || ''),
      });
      note.show();
      return { success: true };
    } catch (err) {
      return { success: false, error: String((err && err.message) || err) };
    }
  });
}

module.exports = { registerDesktopServiceHandlers };
