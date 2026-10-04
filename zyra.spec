# -*- mode: python ; coding: utf-8 -*-
"""
zyra.spec — PyInstaller build for the ZYRA Python backend.

Produces a self-contained `ZYRA-backend` folder (onedir) that
electron-builder ships inside the installed app as `resources/zyra/`.

The bundled backend must NOT depend on:
  * the source repository
  * a developer virtualenv
  * any Python installation on the target machine

Run from the project root:
    .venv\\Scripts\\python.exe -m PyInstaller zyra.spec --noconfirm --clean
"""

from pathlib import Path
from os.path import expanduser
import glob
import os
import sysconfig

PROJECT_ROOT = Path(SPECPATH).resolve()
HOME = expanduser("~")

# ── Files collected from the source tree ─────────────────────────────────────
datas = [
    # The Three.js holographic dashboard served by FastAPI at "/".
    (str(PROJECT_ROOT / "desktop-dashboard"), "desktop-dashboard"),
    # Trained ML phishing classifier (must ship, never regenerated at runtime).
    (str(PROJECT_ROOT / "backend" / "ml_phishing" / "models"), "backend/ml_phishing/models"),
    # `.env.example` documents the optional VirusTotal / Safe Browsing keys.
    (str(PROJECT_ROOT / ".env.example"), "."),
]

# ── Hidden imports ───────────────────────────────────────────────────────────
# Modules imported dynamically (inside functions, plugin registries or by
# third-party libraries), which PyInstaller's static analysis cannot see.
hiddenimports = [
    # uvicorn resolves its event loop / protocol implementations by name.
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.loops.uvloop",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    "websockets.protocol",
    "wsproto",

    # FastAPI/Starlette internals resolved dynamically.
    "fastapi",
    "starlette.middleware.base",
    "starlette.middleware.cors",
    "starlette.responses",
    "starlette.staticfiles",
    "email_validator",

    # speech_recognition + audio stack used by listen.py.
    "speech_recognition",
    "pyaudio",              # absent in this venv; harmless if not installed
    "sounddevice",
    "sounddevice._cffi",

    # TTS / playback.
    "speak",
    "pygame",
    "pygame.mixer",
    "pygame.freetype",
    "pygame.sprite",
    "pygame.image",
    "edge_tts",
    "edge_playback",

    # Screen OCR used by the "analyse the link I am looking at" feature.
    # easyocr imports torchvision at module level, so both must ship or
    # `import easyocr` fails and OCR silently degrades.
    "easyocr",
    "easyocr.easyocr",
    "easyocr.detection",
    "easyocr.recognition",
    "easyocr.utils",
    "easyocr.config",
    "torch",
    "torchvision",
    "torchvision.ops",
    "torchvision.transforms",
    "torch.ao.nn.quantized.dynamic.rnn",
    # easyocr falls back to these when they are importable.
    "six",
    "shapely",
    "pyclipper",
    "ninja",

    # ML phishing classifier.
    "sklearn",
    "sklearn.ensemble",
    "sklearn.ensemble._forest",
    "sklearn.linear_model",
    "sklearn.feature_extraction.text",
    "sklearn.metrics",
    "sklearn.neighbors",
    "sklearn.preprocessing",
    "sklearn.model_selection",
    "sklearn.pipeline",
    "joblib",

    # Image / screen capture.
    "PIL",
    "PIL.Image",
    "PIL.ImageGrab",
    "PIL.ImageFont",
    "mss",
    "screen_ocr",

    # System control helpers used by commands/.
    "pyautogui",
    "pytweening",
    "pyperclip",
    "psutil",
    "winshell",
    "win32api",
    "win32con",
    "win32com",
    "win32gui",
    "win32process",
    "win32service",
    "win32ui",

    # Networking / DNS / HTTP.
    "requests",
    "dns",
    "dns.resolver",
    "dns.reversename",
    "nmap",
    "ollama",
    "pythoncom",
    "pywintypes",

    # Data / config.
    "dotenv",
    "json",
    "certifi",
]

# EasyOCR downloads its detection/recognition weights (~100 MB) into
# `%USERPROFILE%\.EasyOCR` on first use. In development they are already cached
# there; for an installed build that cache is copied into the bundle so OCR
# works offline on a fresh machine.
EASYOCR_CACHE = Path(HOME) / ".EasyOCR" / "model"

if EASYOCR_CACHE.is_dir():
    datas.append((str(EASYOCR_CACHE), "easyocr/model"))
    print(f"[zyra.spec] bundled EasyOCR weights from {EASYOCR_CACHE}")
else:
    print("[zyra.spec] WARNING: EasyOCR model cache not found; OCR will "
          "download its weights on first run.")

# ── Native binaries that PyInstaller's hooks miss ───────────────────────────
# `torchvision` ships its C++ ops in `_C_stable.pyd`; without it EasyOCR fails
# at model init with "operator torchvision::nms does not exist".
binaries = []

_purelib = sysconfig.get_paths()["purelib"]

for _pattern, _dest in (
    ("torchvision/_C*.pyd", "torchvision"),
    ("torchvision/*.dll", "torchvision"),
    ("torch/lib/*.dll", "torch/lib"),
):
    for _hit in glob.glob(os.path.join(_purelib, _pattern)):
        binaries.append((_hit, _dest))

if not any(os.path.basename(b[0]).startswith("_C") for b in binaries):
    print("[zyra.spec] WARNING: torchvision _C extension not found; screen OCR "
          "will be unavailable in the packaged build.")

# Third-party packages PyInstaller has no hook for.
collect_all = ["edge_tts", "easyocr", "pyautogui"]

block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Bundling every scientific DLL is slow and bloats the installer; keep only
    # what PyInstaller plus the collect_all packages below actually need.
    excludes=[
        "tkinter",
        "matplotlib",
        "pytest",
        "IPython",
        "notebook",
        "sphinx",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ZYRA-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX mangles the large ML/runtime DLLs; keep them intact
    console=True,        # Electron reads stdout/stderr for the startup log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ZYRA-backend",
)
