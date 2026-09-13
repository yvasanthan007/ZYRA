/**
 * electron-builder configuration for ZYRA Desktop.
 *
 * Packaging strategy (minimum modification):
 *   - The Electron shell is packaged as a normal Electron app.
 *   - The ZYRA Python project is copied into the install as
 *     "<resources>/zyra" via extraResources so the packaged app can start
 *     the existing backend from the installed copy (or from ZYRA_HOME).
 *   - Python 3 + the project requirements must be available at runtime
 *     (desktop/main.js auto-detects .venv or system python). Native Python
 *     deps (easyocr, pyautogui, python-nmap, PyAudio) cannot be bundled
 *     inside an Electron package.
 */
module.exports = {
  appId: "com.zyra.desktop",
  productName: "ZYRA",
  directories: {
    output: "desktop-dist",
  },
  files: [
    "desktop/main.js",
    "desktop/preload.js",
    "desktop/icon.ico",
    "package.json",
  ],
  extraResources: [
    {
      // Ship the existing ZYRA application (unchanged) with the installer
      from: ".",
      to: "zyra",
      filter: [
        "backend/**",
        "commands/**",
        "memory/**",
        "desktop-dashboard/**",
        "main.py",
        "brain.py",
        "listen.py",
        "speak.py",
        "zyra_handler.py",
        "memory.py",
        "system_monitor.py",
        "nmap_handler.py",
        "nmap_scanner.py",
        "link_analysis.py",
        "screen_ocr.py",
        "requirements.txt",
      ],
    },
  ],
  win: {
    icon: "desktop/icon.ico",
    target: ["nsis"],
  },
  nsis: {
    oneClick: false,
    perMachine: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: "ZYRA",
  },
  linux: {
    icon: "desktop",
    category: "Utility",
    target: ["AppImage"],
  },
  mac: {
    icon: "desktop/icon.icns",
    target: ["dmg"],
    category: "public.app-category.productivity",
  },
};
