"""
ZYRA Startup Script
Checks dependencies and starts the application.
"""

import sys
import os
import importlib
import traceback
from pathlib import Path


# Always run from the directory containing this script.
PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)


# Windows console safety: ensure Unicode output works where possible.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def check_package(package_name, import_name=None):
    """Return True when a required Python package can be imported."""

    if import_name is None:
        import_name = package_name

    try:
        importlib.import_module(import_name)
        print(f"  [OK] {package_name}")
        return True
    except ImportError:
        print(f"  [MISSING] {package_name}")
        return False


def main():
    """Check dependencies and start the ZYRA application."""

    print(
        """
    ======================================
             ZYRA DEPENDENCY CHECK
    ======================================
        """
    )

    print("Checking required packages...\n")

    required_packages = [
        ("edge-tts", "edge_tts"),
        ("pyperclip", "pyperclip"),
        ("fastapi", "fastapi"),
        ("ollama", "ollama"),
        ("psutil", "psutil"),
        ("pyautogui", "pyautogui"),
        ("SpeechRecognition", "speech_recognition"),
        ("pygame", "pygame"),
        ("uvicorn", "uvicorn"),
        ("websockets", "websockets"),
        ("winshell", "winshell"),
        ("pywin32", "win32api"),
        ("easyocr", "easyocr"),
        ("mss", "mss"),
        ("requests", "requests"),
        ("Pillow", "PIL"),
    ]

    missing = []

    for package_name, import_name in required_packages:
        if not check_package(package_name, import_name):
            missing.append(package_name)

    if missing:
        print(f"\nMissing {len(missing)} package(s):")
        for package_name in missing:
            print(f"  - {package_name}")

        print("\nActivate your project's virtual environment and install them:")
        print("  python -m pip install " + " ".join(missing))
        print("\nOr install the project's requirements:")
        print("  python -m pip install -r requirements.txt")

        return False

    print("\nAll required packages are installed.")
    print("\nStarting ZYRA...")
    print("=" * 50)

    try:
        # main.py must define a callable main() function.
        from main import main as run_zyra

        print("\nZYRA is starting.")
        print("  Voice commands: Speak into your microphone")
        print("  Dashboard: The application may open it automatically")
        print("  Shutdown: Say 'exit' or press Ctrl+C\n")

        # Call the application entry point directly.
        run_zyra()

    except KeyboardInterrupt:
        print("\nZYRA shutdown requested.")

    except ImportError as exc:
        print(f"\nCould not import a required module: {exc}")
        print(
            "Check main.py and its imports. "
            "Confirm that main.py defines a callable main() function."
        )
        traceback.print_exc()
        return False

    except Exception as exc:
        print(f"\nError starting ZYRA: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False

    print("\nZYRA has stopped.")
    return True


if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)