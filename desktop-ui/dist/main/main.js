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
const path = __importStar(__webpack_require__(/*! path */ "path"));
const python_bridge_1 = __webpack_require__(/*! ./python-bridge */ "./src/main/python-bridge.ts");
let mainWindow = null;
let pythonBridge = null;
function createWindow() {
    mainWindow = new electron_1.BrowserWindow({
        width: 1200,
        height: 800,
        minWidth: 900,
        minHeight: 600,
        title: 'ZYRA - AI Assistant',
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
        },
    });
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}
electron_1.app.whenReady().then(() => {
    createWindow();
    // Initialize Python bridge
    pythonBridge = new python_bridge_1.PythonBridge();
    pythonBridge.start();
    electron_1.app.on('activate', () => {
        if (electron_1.BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});
electron_1.app.on('window-all-closed', () => {
    if (pythonBridge) {
        pythonBridge.stop();
    }
    if (process.platform !== 'darwin') {
        electron_1.app.quit();
    }
});
// IPC Handlers
// Send message to Python AI
electron_1.ipcMain.handle('ai:chat', async (_event, message) => {
    if (!pythonBridge)
        return 'Error: Python bridge not initialized';
    return pythonBridge.sendCommand({ type: 'chat', data: message });
});
// Execute a system command
electron_1.ipcMain.handle('command:execute', async (_event, command) => {
    if (!pythonBridge)
        return 'Error: Python bridge not initialized';
    return pythonBridge.sendCommand({ type: 'command', data: command });
});
// Remember something
electron_1.ipcMain.handle('memory:remember', async (_event, key, value) => {
    if (!pythonBridge)
        return 'Error: Python bridge not initialized';
    return pythonBridge.sendCommand({ type: 'remember', data: { key, value } });
});
// Recall something
electron_1.ipcMain.handle('memory:recall', async (_event, key) => {
    if (!pythonBridge)
        return null;
    return pythonBridge.sendCommand({ type: 'recall', data: key });
});
// System Monitor metrics
electron_1.ipcMain.handle('system:metrics', async () => {
    if (!pythonBridge)
        return null;
    return pythonBridge.sendCommand({ type: 'system_metrics', data: null });
});
// Get available commands list
electron_1.ipcMain.handle('commands:list', async () => {
    return [
        { id: 'open_chrome', label: 'Open Chrome', category: 'apps' },
        { id: 'open_vscode', label: 'Open VS Code', category: 'apps' },
        { id: 'open_notepad', label: 'Open Notepad', category: 'apps' },
        { id: 'open_calculator', label: 'Open Calculator', category: 'apps' },
        { id: 'open_cmd', label: 'Open CMD', category: 'apps' },
        { id: 'open_powershell', label: 'Open PowerShell', category: 'apps' },
        { id: 'open_task_manager', label: 'Task Manager', category: 'apps' },
        { id: 'open_settings', label: 'Open Settings', category: 'apps' },
        { id: 'open_file_explorer', label: 'File Explorer', category: 'apps' },
        { id: 'open_google', label: 'Open Google', category: 'web' },
        { id: 'open_youtube', label: 'Open YouTube', category: 'web' },
        { id: 'open_github', label: 'Open GitHub', category: 'web' },
        { id: 'open_chatgpt', label: 'Open ChatGPT', category: 'web' },
        { id: 'open_gmail', label: 'Open Gmail', category: 'web' },
        { id: 'open_leetcode', label: 'Open LeetCode', category: 'web' },
        { id: 'open_linkedin', label: 'Open LinkedIn', category: 'web' },
        { id: 'monitor_system', label: 'Monitor System', category: 'system' },
        { id: 'volume_up', label: 'Volume Up', category: 'system' },
        { id: 'volume_down', label: 'Volume Down', category: 'system' },
        { id: 'mute', label: 'Mute', category: 'system' },
        { id: 'screenshot', label: 'Screenshot', category: 'system' },
        { id: 'lock_pc', label: 'Lock PC', category: 'system' },
        { id: 'shutdown', label: 'Shutdown', category: 'system' },
        { id: 'restart', label: 'Restart', category: 'system' },
        { id: 'sleep', label: 'Sleep', category: 'system' },
        { id: 'wifi_on', label: 'Wi-Fi On', category: 'system' },
        { id: 'wifi_off', label: 'Wi-Fi Off', category: 'system' },
        { id: 'empty_recycle_bin', label: 'Empty Recycle Bin', category: 'system' },
        { id: 'current_time', label: 'Current Time', category: 'info' },
        { id: 'current_date', label: 'Current Date', category: 'info' },
        { id: 'play_music', label: 'Play Music', category: 'media' },
        { id: 'open_camera', label: 'Open Camera', category: 'media' },
    ];
});


/***/ },

/***/ "./src/main/python-bridge.ts"
/*!***********************************!*\
  !*** ./src/main/python-bridge.ts ***!
  \***********************************/
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
exports.PythonBridge = void 0;
const child_process_1 = __webpack_require__(/*! child_process */ "child_process");
const path = __importStar(__webpack_require__(/*! path */ "path"));
class PythonBridge {
    constructor() {
        this.process = null;
        this.requestId = 0;
        this.pendingRequests = new Map();
        this.buffer = '';
    }
    start() {
        // __dirname is dist/main/ ; bridge_server.py is at desktop-ui/bridge_server.py
        const scriptPath = path.join(__dirname, '../../bridge_server.py');
        this.process = (0, child_process_1.spawn)('python', [scriptPath], {
            stdio: ['pipe', 'pipe', 'pipe'],
            cwd: path.join(__dirname, '../..'),
        });
        this.process.stdout?.on('data', (data) => {
            this.buffer += data.toString();
            this.processBuffer();
        });
        this.process.stderr?.on('data', (data) => {
            console.error('Python Bridge Error:', data.toString());
        });
        this.process.on('exit', (code) => {
            console.log('Python process exited with code:', code);
            this.process = null;
            // Reject all pending requests
            for (const [, pending] of this.pendingRequests) {
                pending.reject(new Error('Python process exited'));
            }
            this.pendingRequests.clear();
        });
        this.process.on('error', (err) => {
            console.error('Failed to start Python process:', err);
        });
    }
    stop() {
        if (this.process) {
            this.process.kill();
            this.process = null;
        }
    }
    async sendCommand(command) {
        return new Promise((resolve, reject) => {
            if (!this.process || !this.process.stdin) {
                reject(new Error('Python process not running'));
                return;
            }
            const id = ++this.requestId;
            this.pendingRequests.set(id, { resolve, reject });
            const message = JSON.stringify({ id, ...command }) + '\n';
            this.process.stdin.write(message);
        });
    }
    processBuffer() {
        const lines = this.buffer.split('\n');
        // Keep the last incomplete line in the buffer
        this.buffer = lines.pop() || '';
        for (const line of lines) {
            if (!line.trim())
                continue;
            try {
                const response = JSON.parse(line);
                const pending = this.pendingRequests.get(response.id);
                if (pending) {
                    this.pendingRequests.delete(response.id);
                    if (response.success) {
                        pending.resolve(response.data);
                    }
                    else {
                        pending.reject(new Error(response.error || 'Unknown error'));
                    }
                }
            }
            catch (e) {
                console.error('Failed to parse Python response:', line);
            }
        }
    }
    isRunning() {
        return this.process !== null && !this.process.killed;
    }
}
exports.PythonBridge = PythonBridge;


/***/ },

/***/ "child_process"
/*!********************************!*\
  !*** external "child_process" ***!
  \********************************/
(module) {

module.exports = require("child_process");

/***/ },

/***/ "electron"
/*!***************************!*\
  !*** external "electron" ***!
  \***************************/
(module) {

module.exports = require("electron");

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