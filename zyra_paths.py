"""
zyra_paths.py — runtime path resolution for ZYRA.

ZYRA has to run in two very different places:

* **Development** — a source checkout, where every file already lives in the
  project root and can be read and written there.
* **Packaged** — a frozen PyInstaller backend shipped inside an installed
  Electron app, where the code/assets are *read-only* (they live in a temp
  bundle directory) and nothing may be written next to them.

This module is the single place that knows the difference, so no other module
has to guess. Nothing here is machine-specific or hard-coded.

Layout in packaged mode:

    <bundle>/                 read-only: code, desktop-dashboard/, ML models
    %LOCALAPPDATA%/ZYRA/data  read-write: memory + scan/lookup history + output
"""

import os
import sys

APP_NAME = "ZYRA"

#: Environment variable that overrides the writable data directory (used by
#: tests and by anyone who wants ZYRA's data somewhere else).
DATA_DIR_ENV = "ZYRA_DATA_DIR"


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> str:
    """
    Read-only root that contains the bundled assets.

    * frozen  -> the PyInstaller bundle directory (`sys._MEIPASS`).
    * source  -> the directory containing this file (the project root).
    """
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return str(meipass)
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts: str) -> str:
    """Path to a bundled read-only asset, e.g. `desktop-dashboard/index.html`."""
    return os.path.join(resource_root(), *parts)


def data_dir() -> str:
    """
    Writable directory for anything ZYRA creates at runtime.

    * frozen  -> `%LOCALAPPDATA%\\ZYRA\\data` (never inside the app install).
    * source  -> the project root, preserving the existing development layout
                 (`memory/data.json`, `backend/.../url_scan_history.json`, …).
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override and override.strip():
        return os.path.abspath(override.strip())

    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME, "data")

    return resource_root()


def ensure_dir(path: str) -> str:
    """Create `path` (and parents) if needed and return it."""
    try:
        if path:
            os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def writable_path(*parts: str) -> str:
    """
    Absolute path inside the writable data directory, with its parent created.

    Always writes outside the application install directory, so a packaged ZYRA
    installed under `C:\\Program Files` never fails on a read-only file.
    """
    target = os.path.join(data_dir(), *parts)
    ensure_dir(os.path.dirname(target))
    return target


def writable_dir(*parts: str) -> str:
    """A writable directory inside the data directory, created on demand."""
    return ensure_dir(os.path.join(data_dir(), *parts))


def describe() -> dict:
    """Small diagnostics mapping (surfaced in logs / backend startup banner)."""
    return {
        "frozen": is_frozen(),
        "resource_root": resource_root(),
        "data_dir": data_dir(),
    }
