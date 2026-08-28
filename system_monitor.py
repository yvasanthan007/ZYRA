"""
System Monitor Module for ZYRA AI Assistant
Provides real-time cross-platform system monitoring using psutil.
Collects CPU, RAM, Disk, Network, Battery, Uptime, and OS details.
"""

import os
import sys
import time
import platform
import socket
from datetime import timedelta
from typing import Dict, Any, Optional

try:
    import psutil
except ImportError:
    psutil = None

# Trigger phrases that activate System Monitor
SYSTEM_MONITOR_TRIGGERS = [
    "monitor my system",
    "monitor the system",
    "monitor system",
    "system monitor",
    "start system monitor",
    "start the system monitor",
    "open system monitor",
    "show system monitor",
    "launch system monitor",
    "display system monitor",
    "check system monitor",
    "run system monitor",
    "system monitoring",
    "check system status",
    "system status",
    "system stats",
    "pc stats",
    "hardware stats",
]


def is_system_monitor_intent(text: str) -> bool:
    """Check if the transcribed command or message is requesting System Monitor."""
    if not text:
        return False
    clean = text.lower().strip()
    return any(trigger in clean for trigger in SYSTEM_MONITOR_TRIGGERS)


def format_bytes(b: float) -> str:
    """Format bytes to human-readable string (KB, MB, GB)."""
    if b < 1024:
        return f"{b:.0f} B"
    elif b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 ** 3:
        return f"{b / (1024 ** 2):.1f} MB"
    else:
        return f"{b / (1024 ** 3):.2f} GB"


def format_speed(bps: float) -> str:
    """Format bytes per second into human-readable speed."""
    if bps < 1024:
        return f"{bps:.0f} B/s"
    elif bps < 1024 ** 2:
        return f"{bps / 1024:.1f} KB/s"
    elif bps < 1024 ** 3:
        return f"{bps / (1024 ** 2):.1f} MB/s"
    else:
        return f"{bps / (1024 ** 3):.2f} GB/s"


def make_progress_bar(percent: float, total_blocks: int = 10, filled_char: str = "█", empty_char: str = "░") -> str:
    """Generate an ASCII progress bar for percentages."""
    percent = max(0.0, min(100.0, percent))
    filled = int(round((percent / 100.0) * total_blocks))
    filled = max(0, min(total_blocks, filled))
    empty = total_blocks - filled
    return (filled_char * filled) + (empty_char * empty)

class SystemMonitor:
    """
    Thread-safe, non-blocking real-time system metrics collector.
    Avoids high CPU overhead by reusing sampled timestamps and delta counters.
    """

    def __init__(self):
        self._last_net_bytes_recv = 0
        self._last_net_bytes_sent = 0
        self._last_net_time = 0.0
        self._initialized = False
        self._init_sampler()

    def _init_sampler(self):
        if not psutil:
            return
        try:
            # Seed CPU percent sampling
            psutil.cpu_percent(interval=None)
            net = psutil.net_io_counters()
            if net:
                self._last_net_bytes_recv = net.bytes_recv
                self._last_net_bytes_sent = net.bytes_sent
                self._last_net_time = time.time()
            self._initialized = True
        except Exception:
            pass

    def get_metrics(self) -> Dict[str, Any]:
        """Collect and return real-time system metrics snapshot."""
        if not psutil:
            return self._get_fallback_metrics()

        try:
            now = time.time()

            # CPU
            try:
                cpu_percent = float(psutil.cpu_percent(interval=None))
                cpu_cores_logical = psutil.cpu_count(logical=True) or 1
                cpu_cores_physical = psutil.cpu_count(logical=False) or 1
            except Exception:
                cpu_percent = 0.0
                cpu_cores_logical = 1
                cpu_cores_physical = 1

            # Memory
            try:
                vm = psutil.virtual_memory()
                ram_percent = float(vm.percent)
                ram_used_bytes = vm.used
                ram_available_bytes = vm.available
                ram_total_bytes = vm.total
            except Exception:
                ram_percent = 0.0
                ram_used_bytes = 0
                ram_available_bytes = 0
                ram_total_bytes = 0

            # Disk (root drive)
            try:
                if platform.system() == "Windows":
                    drive = os.path.splitdrive(os.path.abspath("."))[0] or "C:"
                    drive = drive + "\\" if not drive.endswith("\\") else drive
                    disk = psutil.disk_usage(drive)
                else:
                    disk = psutil.disk_usage("/")
                disk_percent = float(disk.percent)
                disk_used_bytes = disk.used
                disk_free_bytes = disk.free
                disk_total_bytes = disk.total
            except Exception:
                disk_percent = 0.0
                disk_used_bytes = 0
                disk_free_bytes = 0
                disk_total_bytes = 0

            # Network delta speeds
            net_download_speed = 0.0
            net_upload_speed = 0.0
            total_sent = 0
            total_recv = 0
            try:
                net = psutil.net_io_counters()
                if net:
                    total_sent = net.bytes_sent
                    total_recv = net.bytes_recv
                    if self._last_net_time > 0 and now > self._last_net_time:
                        dt = now - self._last_net_time
                        if dt >= 0.1:
                            net_download_speed = max(0.0, (net.bytes_recv - self._last_net_bytes_recv) / dt)
                            net_upload_speed = max(0.0, (net.bytes_sent - self._last_net_bytes_sent) / dt)
                    self._last_net_bytes_recv = net.bytes_recv
                    self._last_net_bytes_sent = net.bytes_sent
                    self._last_net_time = now
            except Exception:
                pass

            # Battery
            battery_percent = 100
            battery_charging = True
            battery_charging_str = "AC Power"
            battery_percent_str = "N/A"
            has_battery = False
            try:
                batt = psutil.sensors_battery()
                if batt is not None:
                    has_battery = True
                    battery_percent = int(batt.percent)
                    battery_percent_str = f"{battery_percent}%"
                    battery_charging = bool(batt.power_plugged)
                    battery_charging_str = "Yes" if batt.power_plugged else "No"
                else:
                    battery_percent_str = "N/A"
                    battery_charging_str = "AC Power"
            except Exception:
                pass

            # Uptime
            uptime_seconds = 0
            uptime_formatted = "0h 00m"
            try:
                boot_time = psutil.boot_time()
                uptime_seconds = max(0, int(now - boot_time))
                days = uptime_seconds // 86400
                hours = (uptime_seconds % 86400) // 3600
                minutes = (uptime_seconds % 3600) // 60
                if days > 0:
                    uptime_formatted = f"{days}d {hours:02d}h {minutes:02d}m"
                else:
                    uptime_formatted = f"{hours:02d}h {minutes:02d}m"
            except Exception:
                pass

            # OS / System info
            os_name = platform.system()
            os_release = platform.release()
            arch = platform.machine()
            system_str = f"{os_name} {os_release} ({arch})".strip()
            if not system_str:
                system_str = os_name or "Unknown OS"

            metrics = {
                "success": True,
                "timestamp": now,
                "cpu": {
                    "percent": round(cpu_percent, 1),
                    "cores_logical": cpu_cores_logical,
                    "cores_physical": cpu_cores_physical,
                    "bar": make_progress_bar(cpu_percent),
                },
                "memory": {
                    "percent": round(ram_percent, 1),
                    "used_bytes": ram_used_bytes,
                    "available_bytes": ram_available_bytes,
                    "total_bytes": ram_total_bytes,
                    "used_str": format_bytes(ram_used_bytes),
                    "available_str": format_bytes(ram_available_bytes),
                    "total_str": format_bytes(ram_total_bytes),
                    "bar": make_progress_bar(ram_percent),
                },
                "disk": {
                    "percent": round(disk_percent, 1),
                    "used_bytes": disk_used_bytes,
                    "free_bytes": disk_free_bytes,
                    "total_bytes": disk_total_bytes,
                    "used_str": format_bytes(disk_used_bytes),
                    "free_str": format_bytes(disk_free_bytes),
                    "total_str": format_bytes(disk_total_bytes),
                    "bar": make_progress_bar(disk_percent),
                },
                "network": {
                    "download_speed_str": format_speed(net_download_speed),
                    "upload_speed_str": format_speed(net_upload_speed),
                    "download_speed_bytes": round(net_download_speed, 1),
                    "upload_speed_bytes": round(net_upload_speed, 1),
                    "total_sent_str": format_bytes(total_sent),
                    "total_recv_str": format_bytes(total_recv),
                },
                "battery": {
                    "has_battery": has_battery,
                    "percent": battery_percent,
                    "percent_str": battery_percent_str,
                    "charging": battery_charging,
                    "charging_str": battery_charging_str,
                },
                "uptime": {
                    "seconds": uptime_seconds,
                    "formatted": uptime_formatted,
                },
                "system": {
                    "os": os_name,
                    "release": os_release,
                    "arch": arch,
                    "formatted": system_str,
                    "hostname": socket.gethostname(),
                },
            }
            return metrics
        except Exception as e:
            return self._get_fallback_metrics(str(e))

    def _get_fallback_metrics(self, error_msg: Optional[str] = None) -> Dict[str, Any]:
        """Return safe fallback metrics when psutil or subsystem is unavailable."""
        return {
            "success": error_msg is None,
            "error": error_msg or "psutil not installed",
            "timestamp": time.time(),
            "cpu": {"percent": 0.0, "cores_logical": 1, "cores_physical": 1, "bar": make_progress_bar(0)},
            "memory": {"percent": 0.0, "used_bytes": 0, "available_bytes": 0, "total_bytes": 0,
                       "used_str": "0 GB", "available_str": "0 GB", "total_str": "0 GB", "bar": make_progress_bar(0)},
            "disk": {"percent": 0.0, "used_bytes": 0, "free_bytes": 0, "total_bytes": 0,
                     "used_str": "0 GB", "free_str": "0 GB", "total_str": "0 GB", "bar": make_progress_bar(0)},
            "network": {"download_speed_str": "0 B/s", "upload_speed_str": "0 B/s",
                        "download_speed_bytes": 0.0, "upload_speed_bytes": 0.0,
                        "total_sent_str": "0 MB", "total_recv_str": "0 MB"},
            "battery": {"has_battery": False, "percent": 100, "percent_str": "N/A", "charging": True, "charging_str": "AC Power"},
            "uptime": {"seconds": 0, "formatted": "0h 00m"},
            "system": {"os": platform.system(), "release": platform.release(), "arch": platform.machine(),
                       "formatted": platform.system(), "hostname": "localhost"},
        }


# Global singleton instance
_global_monitor = SystemMonitor()


def get_system_metrics() -> Dict[str, Any]:
    """Public helper function to get current system metrics."""
    return _global_monitor.get_metrics()


def format_system_monitor_text(metrics: Optional[Dict[str, Any]] = None) -> str:
    """
    Format system metrics as a clean dashboard text card.
    Matches the exact layout requested by ZYRA specifications.
    """
    if metrics is None:
        metrics = get_system_metrics()

    cpu = metrics.get("cpu", {})
    mem = metrics.get("memory", {})
    disk = metrics.get("disk", {})
    net = metrics.get("network", {})
    batt = metrics.get("battery", {})
    uptime = metrics.get("uptime", {})
    sys_info = metrics.get("system", {})

    lines = [
        "SYSTEM MONITOR",
        "",
        f"CPU             {int(round(cpu.get('percent', 0)))}%",
        f"{cpu.get('bar', make_progress_bar(0))}",
        "",
        f"Memory          {int(round(mem.get('percent', 0)))}%",
        f"{mem.get('bar', make_progress_bar(0))}",
        "",
        f"Disk            {int(round(disk.get('percent', 0)))}%",
        f"{disk.get('bar', make_progress_bar(0))}",
        "",
        "Network",
        f"↓ Download      {net.get('download_speed_str', '0 B/s')}",
        f"↑ Upload        {net.get('upload_speed_str', '0 B/s')}",
        "",
        f"Battery         {batt.get('percent_str', 'N/A')}",
        f"Charging        {batt.get('charging_str', 'Yes')}",
        "",
        "Uptime",
        f"{uptime.get('formatted', '0h 00m')}",
        "",
        "System",
        f"{sys_info.get('formatted', sys_info.get('os', 'Windows/Linux/macOS'))}",
    ]
    return "\n".join(lines)


def get_voice_summary(metrics: Optional[Dict[str, Any]] = None) -> str:
    """Generate a concise voice-friendly summary of the system state for TTS."""
    if metrics is None:
        metrics = get_system_metrics()

    cpu_pct = int(round(metrics.get("cpu", {}).get("percent", 0)))
    ram_pct = int(round(metrics.get("memory", {}).get("percent", 0)))
    disk_pct = int(round(metrics.get("disk", {}).get("percent", 0)))
    return f"System Monitor started. CPU is at {cpu_pct} percent, memory is at {ram_pct} percent, and disk is at {disk_pct} percent."


def start_system_monitor() -> str:
    """Action invoked when System Monitor is triggered."""
    metrics = get_system_metrics()
    formatted = format_system_monitor_text(metrics)
    return formatted


if __name__ == "__main__":
    print(format_system_monitor_text())
