"""
ZYRA Startup Script
Checks dependencies and starts the application
"""
import sys
import subprocess
import importlib

# ── Windows console safety ──────────────────────────────────────────────
# Force UTF-8 output so the ✅/❌/box-drawing prints below never crash with
# UnicodeEncodeError on cp1252 Windows consoles.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

def check_package(package_name, import_name=None):
    """Check if a package is installed."""
    if import_name is None:
        import_name = package_name
    
    try:
        importlib.import_module(import_name)
        print(f"  ✅ {package_name}")
        return True
    except ImportError:
        print(f"  ❌ {package_name} - NOT INSTALLED")
        return False

def main():
    print("""
    ╔══════════════════════════════════════╗
    ║       ZYRA DEPENDENCY CHECK          ║
    ╚══════════════════════════════════════╝
    """)
    
    print("Checking required packages...")
    
    required_packages = [
        ("edge-tts", "edge_tts"),
        ("pyperclip", "pyperclip"),
        ("fastapi", "fastapi"),
        ("ollama", "ollama"),
        ("psutil", "psutil"),
        ("pyautogui", "pyautogui"),
        ("sounddevice", "sounddevice"),
        ("numpy", "numpy"),
        ("faster-whisper", "faster_whisper"),
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
        print(f"\n❌ Missing {len(missing)} package(s): {', '.join(missing)}")
        print("\n📦 Install them with:")
        print(f"   pip install {' '.join(missing)}")
        print("\n   Or install all requirements:")
        print("   pip install -r requirements.txt")
        return False
    
    print("\n✅ All required packages are installed!")
    print("\n🚀 Starting ZYRA...")
    print("=" * 50)
    
    # Import and run main
    try:
        from main import main as run_zyra
        # Note: main.py uses if __name__ == "__main__" so we need to exec it
        import main
        import threading
        
        # Start in a way that works
        print("\n✨ ZYRA is starting...")
        print("   🎤 Voice commands: Speak into your microphone")
        print("   🌐 Dashboard: Will open in browser")
        print("   ⌨️  Say 'exit' or press Ctrl+C to quit\n")
        
        # Execute main
        exec(open("main.py").read())
        
    except KeyboardInterrupt:
        print("\n\n👋 ZYRA shutdown complete")
    except Exception as e:
        print(f"\n❌ Error starting ZYRA: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    main()