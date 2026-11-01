/******/ (() => { // webpackBootstrap
/******/ 	"use strict";
/******/ 	var __webpack_modules__ = ({

/***/ "./src/main/main.ts"
/*!**************************!*\
  !*** ./src/main/main.ts ***!
  \**************************/
(__unused_webpack_module, exports, __webpack_require__) {


var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", ({ value: true }));
const electron_1 = __webpack_require__(/*! electron */ "electron");
const http = __importStar(__webpack_require__(/*! http */ "http"));
const path = __importStar(__webpack_require__(/*! path */ "path"));
const BACKEND_HOST = '127.0.0.1';
const BACKEND_PORT = 8080;
const REQUEST_TIMEOUT_MS = 15000;
const CHAT_REQUEST_TIMEOUT_MS = 90000;
const APPROVED_PATHS = new Set([
    '/api/cyberllm/status',
    '/api/cyberllm/phishing',
    '/api/cyberllm/chat',
    '/api/health',
    '/api/ai/status',
    '/api/chat',
    '/api/command',
    '/api/voice',
    '/api/speak',
    '/api/speak/stop',
    '/api/analyze-link',
    '/api/system-metrics',
    '/api/ml/phishing',
    '/api/ml/phishing/model',
    '/api/ml/phishing/dataset',
    '/api/ml/phishing/capture',
    '/api/dns/lookup',
    '/api/dns/result',
    '/api/dns/report',
    '/api/dns/history',
]);
let mainWindow = null;
function forwardToBackend(method, apiPath, payload) {
    return new Promise((resolve) => {
        if (!APPROVED_PATHS.has(apiPath)) {
            resolve({
                success: false,
                error: 'API path is not approved.',
            });
            return;
        }
        const body = method === 'POST' && payload !== undefined
            ? JSON.stringify(payload)
            : undefined;
        const timeoutMs = apiPath === '/api/cyberllm/chat'
            ? CHAT_REQUEST_TIMEOUT_MS
            : REQUEST_TIMEOUT_MS;
        const req = http.request({
            hostname: BACKEND_HOST,
            port: BACKEND_PORT,
            path: apiPath,
            method,
            headers: {
                Accept: 'application/json',
                ...(body
                    ? {
                        'Content-Type': 'application/json',
                        'Content-Length': Buffer.byteLength(body),
                    }
                    : {}),
            },
        }, (res) => {
            let responseText = '';
            res.setEncoding('utf8');
            res.on('data', (chunk) => {
                responseText += chunk;
            });
            res.on('end', () => {
                const statusCode = res.statusCode ?? 500;
                let responseBody = responseText;
                try {
                    responseBody = responseText
                        ? JSON.parse(responseText)
                        : {};
                }
                catch {
                    // Preserve a non-JSON response as text.
                }
                resolve({
                    success: statusCode >= 200 && statusCode < 300,
                    statusCode,
                    body: responseBody,
                    ...(statusCode >= 400
                        ? { error: `Backend returned HTTP ${statusCode}` }
                        : {}),
                });
            });
        });
        req.setTimeout(timeoutMs, () => {
            req.destroy(new Error('Backend request timed out.'));
        });
        req.on('error', (error) => {
            resolve({
                success: false,
                error: error.message,
            });
        });
        if (body) {
            req.write(body);
        }
        req.end();
    });
}
function registerBackendRequestHandler() {
    electron_1.ipcMain.removeHandler('backend:request');
    electron_1.ipcMain.handle('backend:request', async (_event, method, apiPath, payload) => {
        if (method !== 'GET' && method !== 'POST') {
            return {
                success: false,
                error: 'Only GET and POST methods are permitted.',
            };
        }
        if (typeof apiPath !== 'string' || !APPROVED_PATHS.has(apiPath)) {
            return {
                success: false,
                error: 'API path is not approved.',
            };
        }
        return forwardToBackend(method, apiPath, payload);
    });
}
/**
 * Connects the renderer's aiChat() call to the CyberLLM chat API.
 * The renderer expects a string, so this returns the generated answer.
 */
function registerAIChatHandler() {
    electron_1.ipcMain.removeHandler('ai:chat');
    electron_1.ipcMain.handle('ai:chat', async (_event, message) => {
        if (typeof message !== 'string' || !message.trim()) {
            throw new Error('Please enter a message.');
        }
        const result = await forwardToBackend('POST', '/api/cyberllm/chat', { message: message.trim() });
        if (!result.success) {
            throw new Error(result.error ?? 'Unable to contact the Zyra backend.');
        }
        const body = result.body;
        if (!body || typeof body !== 'object') {
            throw new Error('The backend returned an invalid chat response.');
        }
        if (body.success === false) {
            throw new Error(body.error ??
                body.detail ??
                'CyberLLM could not generate a response.');
        }
        const answer = body.data?.answer ??
            body.data?.response ??
            body.data?.message ??
            body.answer ??
            body.response ??
            body.message;
        if (typeof answer !== 'string' || !answer.trim()) {
            throw new Error(body.detail ??
                body.error ??
                'CyberLLM returned an empty answer.');
        }
        return answer.trim();
    });
}
function createWindow() {
    const preloadPath = path.join(__dirname, '../preload/preload.js');
    const rendererPath = path.join(__dirname, '../renderer/index.html');
    mainWindow = new electron_1.BrowserWindow({
        width: 1280,
        height: 850,
        minWidth: 900,
        minHeight: 600,
        show: true,
        webPreferences: {
            preload: preloadPath,
            contextIsolation: true,
            nodeIntegration: false,
        },
    });
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
    void mainWindow.loadFile(rendererPath);
}
electron_1.app.whenReady().then(() => {
    registerBackendRequestHandler();
    registerAIChatHandler();
    createWindow();
    electron_1.app.on('activate', () => {
        if (electron_1.BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});
electron_1.app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        electron_1.app.quit();
    }
});


/***/ },

/***/ "electron"
/*!***************************!*\
  !*** external "electron" ***!
  \***************************/
(module) {

module.exports = require("electron");

/***/ },

/***/ "http"
/*!***********************!*\
  !*** external "http" ***!
  \***********************/
(module) {

module.exports = require("http");

/***/ },

/***/ "path"
/*!***********************!*\
  !*** external "path" ***!
  \***********************/
(module) {

module.exports = require("path");

/***/ }

/******/ 	});
/************************************************************************/
/******/ 	// The module cache
/******/ 	const __webpack_module_cache__ = {};
/******/ 	
/******/ 	// The require function
/******/ 	function __webpack_require__(moduleId) {
/******/ 		// Check if module is in cache
/******/ 		const cachedModule = __webpack_module_cache__[moduleId];
/******/ 		if (cachedModule !== undefined) {
/******/ 			return cachedModule.exports;
/******/ 		}
/******/ 		// Create a new module (and put it into the cache)
/******/ 		const module = __webpack_module_cache__[moduleId] = {
/******/ 			// no module.id needed
/******/ 			// no module.loaded needed
/******/ 			exports: {}
/******/ 		};
/******/ 	
/******/ 		// Execute the module function
/******/ 		if (!(moduleId in __webpack_modules__)) {
/******/ 			delete __webpack_module_cache__[moduleId];
/******/ 			const e = new Error("Cannot find module '" + moduleId + "'");
/******/ 			e.code = 'MODULE_NOT_FOUND';
/******/ 			throw e;
/******/ 		}
/******/ 		__webpack_modules__[moduleId].call(module.exports, module, module.exports, __webpack_require__);
/******/ 	
/******/ 		// Return the exports of the module
/******/ 		return module.exports;
/******/ 	}
/******/ 	
/************************************************************************/
/******/ 	
/******/ 	// startup
/******/ 	// Load entry module and return exports
/******/ 	// This entry module is referenced by other modules so it can't be inlined
/******/ 	let __webpack_exports__ = __webpack_require__("./src/main/main.ts");
/******/ 	
/******/ })()
;
//# sourceMappingURL=main.js.map