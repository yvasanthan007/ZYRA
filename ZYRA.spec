# PyInstaller build definition for the existing ZYRA source project.
# The native desktop entry point does not import the legacy voice/browser
# runtime, so exclude its optional OCR and speech stacks from the release build.
hiddenimports = [
    "backend.url_analyzer",
    "backend.url_analyzer.analyzer",
    "backend.url_analyzer.history",
    "backend.url_analyzer.report_generator",
    "backend.nmap_service",
    "backend.nmap_report",
    "backend.zyra_bridge",
    "PySide6.QtSvg",
]

app = Analysis(
    ["desktop_app.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("backend/url_analyzer/url_scan_history.json", "backend/url_analyzer"),
        ("backend/dns_lookup/dns_lookup_history.json", "backend/dns_lookup"),
        ("memory/data.json", "memory"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "easyocr", "torch", "torchvision", "cv2", "tensorflow", "pandas",
        "matplotlib", "pytest", "speech_recognition", "sounddevice",
        "pyautogui", "mss", "listen", "screen_ocr", "nmap_handler",
    ],
    noarchive=False,
)
pyz = PYZ(app.pure)
exe = EXE(
    pyz,
    app.scripts,
    [],
    exclude_binaries=True,
    name="ZYRA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    app.binaries,
    app.datas,
    strip=False,
    upx=True,
    name="ZYRA",
)
