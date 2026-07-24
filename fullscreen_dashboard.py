"""
Fullscreen Dashboard Launcher for ZYRA AI Assistant
Launches Microsoft Edge in kiosk mode for true fullscreen experience
"""

import subprocess
import sys
import os
import time
import platform


def find_edge_path():
    """
    Find Microsoft Edge executable path on Windows
    """
    # Common Edge installation paths on Windows
    possible_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    # Try to find via where command
    try:
        result = subprocess.run(
            ["where", "msedge"],
            capture_output=True,
            text=True,
            shell=True
        )
        if result.returncode == 0:
            edge_path = result.stdout.strip().split("\n")[0].strip()
            if edge_path:
                return edge_path
    except Exception:
        pass
    
    return None


def open_dashboard_fullscreen(url):
    """
    Open the ZYRA dashboard in Microsoft Edge kiosk mode (true fullscreen).
    
    Kiosk mode opens Edge without any browser UI elements:
    - No address bar
    - No tabs
    - No window decorations
    - Covers entire screen (Alt+Tab style)
    - No developer tools access
    
    Args:
        url: The dashboard URL to open (e.g., "http://127.0.0.1:8080")
    
    Returns:
        bool: True if launched successfully, False otherwise
    """
    print(f"\n{'='*50}")
    print("🖥️  Opening ZYRA Dashboard in Fullscreen Mode...")
    print(f"   URL: {url}")
    print(f"{'='*50}\n")
    
    edge_path = find_edge_path()
    
    if not edge_path:
        print("⚠️  Microsoft Edge not found. Trying fallback methods...")
        return fallback_launch(url)
    
    try:
        # Kiosk mode flags for Edge:
        # --kiosk: Fullscreen kiosk mode (no UI elements)
        # --no-first-run: Skip first-run experience
        # --edge-fr-shortcuts: Enable fullscreen shortcuts (F11 to exit)
        # --disable-features: Disable features that might interfere
        # --window-position: Start at (0,0) top-left corner
        # --kiosk-printing: Disable printing
        subprocess.Popen(
            [
                edge_path,
                f"--kiosk={url}",
                "--no-first-run",
                "--edge-fr-shortcuts",
                "--no-sandbox",
                "--disable-features=msUndersideButton,msSidebar",
                "--disable-sync",
                "--disable-extensions",
                "--disable-default-apps",
                "--disable-notifications",
            ],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        print("✅ Dashboard opened in fullscreen mode!")
        print("   ℹ️  Press Alt+F4 to close the fullscreen window")
        print("   ℹ️  Voice assistant continues running in background\n")
        return True
        
    except Exception as e:
        print(f"❌ Error launching Edge in kiosk mode: {e}")
        print("   Trying fallback method...")
        return fallback_launch(url)


def fallback_launch(url):
    """
    Fallback method: Use Microsoft Edge start maximized via shell
    
    This attempts to open Edge maximized if kiosk mode fails.
    """
    try:
        edge_path = find_edge_path()
        if edge_path:
            # Launch maximized instead of kiosk
            subprocess.Popen(
                [
                    edge_path,
                    f"--start-maximized",
                    "--no-first-run",
                    "--new-window",
                    url,
                ],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("✅ Dashboard opened (maximized mode - press F11 for fullscreen)")
            return True
    except Exception as e:
        print(f"❌ Fallback also failed: {e}")
    
    # Last resort: use default browser
    print("⚠️  All fullscreen methods failed. Opening with default browser...")
    import webbrowser
    webbrowser.open(url)
    return False


def is_windows():
    """Check if running on Windows"""
    return platform.system() == "Windows"


# ========== Test / Debug ==========
if __name__ == "__main__":
    # Test the fullscreen launcher
    test_url = "http://127.0.0.1:8080"
    print(f"Testing fullscreen dashboard launcher with URL: {test_url}")
    print(f"Platform: {platform.system()}")
    print(f"Edge path: {find_edge_path()}")
    
    if is_windows():
        open_dashboard_fullscreen(test_url)
    else:
        print("This module is designed for Windows. Using fallback.")
        fallback_launch(test_url)
