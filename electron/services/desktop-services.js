/**
 * Future-ready desktop services for ZYRA.
 *
 * IMPORTANT: these are thin proxies over the EXISTING FastAPI backend
 * (backend/server.py). No new scanning/monitoring features are implemented
 * here — the architecture is only prepared so Nmap, DNS, system info,
 * network info, and notifications can be wired to native code later.
 */
'use strict';

const http = require('http');
const https = require('https');

function requestJson(baseUrl, method, pathname, body) {
  const url = new URL(pathname, baseUrl);
  const lib = url.protocol === 'https:' ? https : http;
  const payload = body === undefined ? null : JSON.stringify(body);
  return new Promise((resolve, reject) => {
    const req = lib.request(
      {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname + url.search,
        method,
        headers: {
          'Content-Type': 'application/json',
          ...(payload ? { 'Content-Length': Buffer.byteLength(payload) } : {}),
        },
      },
      (res) => {
        let raw = '';
        res.on('data', (chunk) => { raw += chunk; });
        res.on('end', () => {
          try {
            resolve(raw ? JSON.parse(raw) : null);
          } catch (err) {
            reject(err);
          }
        });
      }
    );
    req.on('error', reject);
    req.setTimeout(15000, () => req.destroy(new Error('desktop service timeout')));
    if (payload) req.write(payload);
    req.end();
  });
}

async function getSystemInfo(baseUrl) {
  // Existing endpoint: GET /api/system/metrics (also /api/system-metrics).
  return requestJson(baseUrl, 'GET', '/api/system/metrics');
}

async function getNetworkInfo(baseUrl) {
  // No dedicated network endpoint yet: reuse nmap state + system metrics so
  // the channel exists for a future native implementation.
  const [system, nmap] = await Promise.all([
    requestJson(baseUrl, 'GET', '/api/system/metrics').catch((e) => ({ success: false, error: String(e) })),
    requestJson(baseUrl, 'GET', '/api/nmap/state').catch((e) => ({ success: false, error: String(e) })),
  ]);
  return { success: true, system, nmap };
}

async function dnsLookup(baseUrl, domain, recordType) {
  // Existing endpoint: POST /api/dns/lookup { domain, record_type?, ... }.
  const cleanDomain = String(domain || '').trim();
  if (!cleanDomain) throw new Error('Domain is required');
  return requestJson(baseUrl, 'POST', '/api/dns/lookup', {
    domain: cleanDomain,
    record_type: recordType || 'A',
    source: 'desktop',
  });
}

async function nmapScan(baseUrl, payload) {
  // Existing endpoint: POST /api/nmap/scan { operation, target, ports? }.
  const body = payload && typeof payload === 'object' ? payload : {};
  if (!body.operation) throw new Error('Nmap operation is required');
  if (!body.target) throw new Error('Nmap target is required');
  return requestJson(baseUrl, 'POST', '/api/nmap/scan', { ...body, source: 'desktop' });
}

module.exports = { getSystemInfo, getNetworkInfo, dnsLookup, nmapScan };
