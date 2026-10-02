/**
 * Secure preload bridge. Only whitelisted desktop APIs are exposed.
 * No Node.js / filesystem access leaks to the renderer.
 */
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('zyraAPI', {
  isDesktop: true,

  window: {
    minimize: () => ipcRenderer.invoke('zyra-window:minimize'),
    maximize: () => ipcRenderer.invoke('zyra-window:maximize'),
    restore: () => ipcRenderer.invoke('zyra-window:restore'),
    close: () => ipcRenderer.invoke('zyra-window:close'),
    isMaximized: () => ipcRenderer.invoke('zyra-window:is-maximized'),
    onMaximizedChanged: (listener) => {
      if (typeof listener !== 'function') return () => {};
      const handler = (_event, value) => listener(!!value);
      ipcRenderer.on('zyra-window:maximized-changed', handler);
      return () => ipcRenderer.removeListener('zyra-window:maximized-changed', handler);
    },
  },

  system: {
    // Served by the existing FastAPI backend; Electron only proxies the call.
    getInfo: () => ipcRenderer.invoke('zyra-system:info'),
    getNetwork: () => ipcRenderer.invoke('zyra-system:network'),
  },

  net: {
    // Future-ready stubs. Backed by existing backend services when available.
    dnsLookup: (domain, recordType) =>
      ipcRenderer.invoke('zyra-net:dns-lookup', { domain, recordType }),
    nmapScan: (payload) => ipcRenderer.invoke('zyra-net:nmap-scan', payload || {}),
  },

  notify: (title, body) => ipcRenderer.invoke('zyra:notify', { title, body }),

  backend: {
    getUrl: () => ipcRenderer.invoke('zyra-backend:url'),
    onStatus: (listener) => {
      if (typeof listener !== 'function') return () => {};
      const handler = (_event, status) => listener(status);
      ipcRenderer.on('zyra-backend:status', handler);
      return () => ipcRenderer.removeListener('zyra-backend:status', handler);
    },
  },
});
