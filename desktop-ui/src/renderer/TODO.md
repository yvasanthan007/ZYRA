# Dashboard Integration Plan - Implementation Steps

## Steps
1. [ ] Replace `src/renderer/index.html` - Add Three.js CDN, canvas, bezel structure, taskbar, desktop elements
2. [ ] Rewrite `src/renderer/styles/app.css` - Complete dashboard CSS (bezel, screen, taskbar, plants, mouse, Three.js canvas)
3. [ ] Update `src/renderer/App.tsx` - Integrate React components inside the screen area of the laptop bezel
4. [ ] Verify the Electron build compiles and all components render correctly

## Files to Keep UNCHANGED (Zero modifications)
- All Python files (bridge_server.py, main.py, brain.py, listen.py, speak.py, commands/*)
- All React component files (ChatView.tsx, CommandPanel.tsx, VoiceControl.tsx, Settings.tsx, Sidebar.tsx)
- Electron main process (main.ts, preload.ts, python-bridge.ts)
- package.json, webpack.config.js, tsconfig.json
- types.d.ts, index.tsx
