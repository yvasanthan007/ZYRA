"""
System Monitor Module for ZYRA AI Assistant
Provides real-time cross-platform system monitoring using psutil.
Collects CPU, RAM, Disk, Network, Battery, Uptime, and OS details.
"""

import os
import re
import sys
import time
import platform
import socket
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import deque

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


# ──────────────────────────────────────────────
# Natural-language query classification
# ──────────────────────────────────────────────
#
# SYSTEM_MONITOR_TRIGGERS only covers explicit "open/show the monitor" wording.
# Users also ask direct questions ("what is my cpu usage?", "is my disk full?",
# "how long has my pc been on?") which used to fall through to the language
# model — it has no access to this machine, so it refused or invented numbers.
# classify_system_query() maps those questions onto a metric topic so they can
# be answered from real psutil data instead.

# Topics deliberately ordered most-specific-first: "what processes use the most
# memory" must resolve to 'processes' (not 'ram'), and "is my cpu temperature
# high" to 'temperature' (not 'cpu').
_TOPIC_PATTERNS = (
    ("processes", r"\b(process(es)?|tasks?|apps?|applications?|programs?)\b"),
    ("temperature", r"\b(temperature|temps?|thermals?|overheat(ing)?|fans?|too hot)\b"),
    ("battery", r"\b(batter(y|ies)|charging|charger|power (level|status)|plugged in|ac power)\b"),
    ("uptime", r"\b(uptime|up time|how long (has|have|is|since)|boot(ed)?( time)?|"
                r"since (the )?(last )?(boot|restart|reboot)|running for)\b"),
    ("network", r"\b(network|internet|bandwidth|download(ing)?|upload(ing)?|wifi|wi-?fi|"
                r"ethernet|ip(v4)? address|local ip|connection speed|mbps)\b"),
    ("disk", r"\b(disk|disks|drive[s]?|storage|hard ?drive|ssd|partitions?|"
              r"(disk|storage|drive) space|how full)\b"),
    ("ram", r"\b(ram|memory|mem)\b"),
    ("cpu", r"\b(cpu|processor|cores?|threads?|ghz|utilisation|utilization)\b"),
    ("system", r"\b(system info(rmation)?|os( version)?|operating system|windows version|"
              r"platform|hostname|machine name|specs?|hardware)\b"),
    ("overall", r"\b(system|pc|computer|laptop|machine|device|performance|resources?|"
                r"health|status|stats?|healthy|slow|laggy|lag|freez(e|ing)|degraded)\b"),
)

# A message must look like a question/request *about* the machine before any
# topic rule is trusted, otherwise "python memory usage" would hit 'ram'.
_QUERY_HINTS = (
    "how much", "how many", "how full", "how fast", "how hot", "how long",
    "what is", "what's", "whats", "what are", "which", "is my", "is the",
    "are my", "do i have", "does my", "am i", "why", "how", "check",
    "show me", "show my", "tell me", "give me", "report", "usage", "used",
    "using", "free", "available", "remaining", "left", "level", "percent",
    "%", "status", "performance", "info", "resources", "health", "stats",
)

# Metric words that appear in questions about *other* things — never route these.
_UNRELATED_PATTERNS = (
    r"\b(python|java|javascript|typescript|node|nodejs|c\+\+|rust|golang|docker|"
    r"kubernetes|excel|sql|kotlin|swift|ruby|php|react)\b",
    r"\b(cpu|gpu)\s+vs\b",
    r"\b(buy|purchase|upgrade|install|recommend|suggest|best|cheapest|compare|"
    r"review|price|spec sheet)\b",
    r"\bhow (do|can|should) i\b.*\b(free|clear|clean|increase|reduce|optimize|optimise|"
    r"speed up|boost|fix)\b",
    r"\b(code|script|function|class|variable|array|list|dict|dictionary|library|"
    r"api|component|design|pattern|architecture|syntax|algorithm)\b",
    # General-knowledge questions that merely share a metric word.
    r"\b(status|situation|news|update)s? (of|on|about|for) (my|our|the)? ?"
    r"(order|shipment|delivery|package|job|application|resume|cv|homework|"
    r"assignment|exam|class|course|repo|repository|project|task|ticket|issue|"
    r"bill|invoice|account|password|email|inbox|calendar|meeting)\b",
    r"\b(how much|what) (memory|ram|disk space|storage) (does|do|would|will|is) "
    r"(a|an|the|chrome|firefox|edge|word|excel|node|java|python)\b",
    r"\b(memory|performance|health) (tips?|advice|problems?|issues?)\b",
    r"\bwhat (is|are) (the )?(status|situation) of\b",
    r"\b(tips?|advice|guide|examples?|benefits?|drawbacks?) (for|on|about) (my )?"
    r"(health|fitness|studying|sleep|diet|exercise|career)\b",
)

# The sentence must be *about this machine*. Two ways to say that:
#   1. a self-reference  — "my pc", "this machine", "my laptop"
#   2. a possessive metric — "my ram", "my disk space", "my battery"
# Without one of these, bare words like "status", "health" or "memory" belong to
# whatever the user is actually asking about (their order, a browser tab, a
# programming language) and the language model must handle it instead.
_SELF_PATTERNS = (
    # "my pc" / "this computer" / "our laptop" / "the system"
    r"\b(my|this|our|the|your)\s+(pc|computer|laptop|desktop|workstation|mac|"
    r"macbook|system|machine|device|box|server|hardware)\b",
    # "my cpu" / "my ram" / "my disk space" / "my battery"
    r"\b(my|this|our)\s+(cpu|processor|cores?|ram|memory|disk|disks|drive|drives|"
    r"storage|ssd|battery|uptime|temperature|thermals?|network|wifi|internet|"
    r"ethernet|bandwidth|screen|display|performance|speed)\b",
    # First-person complaints: "my pc is slow", "my laptop keeps crashing".
    r"\b(my|this|the)\s+\w{0,12}\s*(is|are|feels?|seems?|keeps?|started?|was|has|have)\b"
    r"[a-z ]{0,24}\b(slow|laggy|lagging|freez\w*|crash\w*|hang\w*|overheat\w*|"
    r"stutter\w*|unresponsive|unusable|stuck|choking|struggling)\b",
    # "everything on my pc is slow", "this machine feels slow"
    r"\b(everything|anything|it|this|that|here)\b[^.?!]{0,40}\b(is|are|feels?|"
    r"seems?|running)\b[^.?!]{0,20}\b(slow|laggy|freez\w*|crash\w*|hot|heavy)\b",
)

# A question shape that, combined with a metric topic, is safe to route even
# without an explicit "my" — e.g. "how long has the pc been on".
_QUESTION_HINT_RE = re.compile(
    r"\b(how much|how many|how full|how fast|how hot|how long|what(?:'s| is| are)|"
    r"whats|which|is (?:my|the)|are (?:my|the)|am i|why is|why are|why does|"
    r"why do|check|show me|show my|tell me|give me|report|usage|used|using|"
    r"left|remaining|available|currently|right now|at the moment)\b"
)


def classify_system_query(text: str) -> Optional[str]:
    """Classify a message as a question about this machine.

    Returns one of 'cpu', 'ram', 'disk', 'network', 'battery', 'uptime',
    'temperature', 'processes', 'system', 'overall', or None when the text is
    not about this machine's state (so normal chat stays with the AI brain).
    """
    if not text:
        return None
    clean = " ".join(str(text).lower().split())
    if not clean:
        return None

    # An explicit "monitor/open/show system monitor" request means the card.
    if any(trigger in clean for trigger in SYSTEM_MONITOR_TRIGGERS):
        return "overall"

    for pattern in _UNRELATED_PATTERNS:
        if re.search(pattern, clean):
            return None

    # Must be phrased as a question/request ...
    if not _QUESTION_HINT_RE.search(clean):
        return None
    # ... *and* be about this machine. Without the self-reference check a bare
    # "status"/"health"/"memory" word was enough to hijack ordinary chat.
    if not any(re.search(pattern, clean) for pattern in _SELF_PATTERNS):
        return None

    for topic, pattern in _TOPIC_PATTERNS:
        if re.search(pattern, clean):
            return topic
    return None


def is_system_monitor_intent(text: str) -> bool:
    """True when the text asks about this machine or requests the monitor.

    Covers the classic trigger phrases *and* natural questions about CPU, RAM,
    disk, network, battery, uptime, processes and temperatures.
    """
    return classify_system_query(text) is not None


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


def analyze_system_health(
    cpu_pct: float,
    ram_pct: float,
    disk_pct: float,
    *,
    history: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Continuously analyze collected metrics for unusual resource consumption or system changes.

    Supports sustained-usage detection: when a rolling window of recent samples
    (history) is supplied, warnings can reflect resource pressure that has
    persisted over an extended period instead of a single snapshot.

    Returns status: 'NORMAL', 'LOW ACTIVITY', 'HIGH RESOURCE USAGE', or 'WARNING', along with description.
    Note: High resource usage is never attributed to malware or security threats.
    """
    # ── Sustained (multi-sample) evaluation over the rolling window ──
    sustained_cpu = False
    sustained_ram = False
    cpu_sustained_avg = 0.0
    ram_sustained_avg = 0.0
    if history is not None:
        try:
            recent = list(history)[-20:]
            if recent:
                cpu_samples = [float(s.get("cpu", 0.0)) for s in recent]
                ram_samples = [float(s.get("ram", 0.0)) for s in recent]
                min_hits = max(4, int(len(recent) * 0.75))
                sustained_cpu = sum(1 for c in cpu_samples if c >= 85.0) >= min_hits
                sustained_ram = sum(1 for r in ram_samples if r >= 88.0) >= min_hits
                cpu_sustained_avg = sum(cpu_samples) / len(cpu_samples)
                ram_sustained_avg = sum(ram_samples) / len(ram_samples)
        except Exception:
            sustained_cpu = False
            sustained_ram = False

    if cpu_pct >= 90.0:
        status = "WARNING"
        description = f"CPU usage has remained high at {int(round(cpu_pct))}%. Heavy compute workload active."
        level = "warning"
    elif ram_pct >= 92.0:
        status = "WARNING"
        description = f"Memory usage is critically high at {int(round(ram_pct))}%. System is near physical memory capacity."
        level = "warning"
    elif disk_pct >= 95.0:
        status = "WARNING"
        description = f"Primary disk is nearly full at {int(round(disk_pct))}%. Consider freeing up disk space."
        level = "warning"
    elif sustained_cpu:
        status = "WARNING"
        description = (
            f"CPU usage has remained above 85% for an extended period "
            f"(average {int(round(cpu_sustained_avg))}% over recent samples). "
            "A sustained heavy workload is active."
        )
        level = "warning"
    elif sustained_ram:
        status = "WARNING"
        description = (
            f"Memory usage has stayed critically high for an extended period "
            f"(average {int(round(ram_sustained_avg))}% over recent samples)."
        )
        level = "warning"
    elif cpu_pct >= 75.0 or ram_pct >= 80.0:
        status = "HIGH RESOURCE USAGE"
        reasons = []
        if cpu_pct >= 75.0:
            reasons.append(f"CPU at {int(round(cpu_pct))}%")
        if ram_pct >= 80.0:
            reasons.append(f"RAM at {int(round(ram_pct))}%")
        description = f"Elevated load: {', '.join(reasons)}. Active processes are consuming significant resources."
        level = "elevated"
    elif cpu_pct <= 10.0 and ram_pct <= 45.0:
        status = "LOW ACTIVITY"
        description = "System is idle with minimal background resource consumption."
        level = "low"
    else:
        status = "NORMAL"
        description = "CPU and memory usage are within normal ranges."
        level = "normal"

    return {
        "status": status,
        "description": description,
        "level": level,
        "cpu_pct": cpu_pct,
        "ram_pct": ram_pct,
        "disk_pct": disk_pct,
        "sustained": bool(sustained_cpu or sustained_ram),
    }

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
        # Rolling sample window (~60s at the dashboard's 1.5s poll) used for
        # sustained-usage analysis. Bounded so memory usage stays tiny.
        self._history = deque(maxlen=40)
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

            # Rolling history for sustained-usage analysis (bounded, low memory)
            self._history.append({"cpu": cpu_percent, "ram": ram_percent, "ts": now})

            # System Health Analysis (includes sustained multi-sample detection)
            analysis = analyze_system_health(cpu_percent, ram_percent, disk_percent, history=self._history)

            metrics = {
                "success": True,
                "timestamp": now,
                "analysis": analysis,
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
            "analysis": {
                "status": "NORMAL",
                "description": "System monitoring initialized.",
                "level": "normal",
                "cpu_pct": 0.0,
                "ram_pct": 0.0,
                "disk_pct": 0.0,
            },
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
    analysis = metrics.get("analysis", {})

    lines = [
        "SYSTEM MONITOR",
        "",
        f"CPU             {int(round(cpu.get('percent', 0)))}%",
        f"{cpu.get('bar', make_progress_bar(0))}",
        "",
        f"RAM             {int(round(mem.get('percent', 0)))}%",
        f"Used: {mem.get('used_str', '0 GB')} / {mem.get('total_str', '0 GB')}",
        f"{mem.get('bar', make_progress_bar(0))}",
        "",
        f"DISK            {int(round(disk.get('percent', 0)))}%",
        f"Used: {disk.get('used_str', '0 GB')} / {disk.get('total_str', '0 GB')}",
        f"{disk.get('bar', make_progress_bar(0))}",
        "",
        "NETWORK",
        f"↓ Download      {net.get('download_speed_str', '0 B/s')}",
        f"↑ Upload        {net.get('upload_speed_str', '0 B/s')}",
        "",
        f"BATTERY         {batt.get('percent_str', 'N/A')}",
        f"Charging:       {batt.get('charging_str', 'Yes').upper()}",
        "",
        "UPTIME",
        f"{uptime.get('formatted', '0h 00m')}",
        "",
        "SYSTEM",
        f"OS:   {sys_info.get('os', 'Windows')}",
        f"Host: {sys_info.get('hostname', 'localhost')}",
        "",
        f"System Status: {analysis.get('status', 'NORMAL')}",
        f"{analysis.get('description', 'CPU and memory usage are within normal ranges.')}",
    ]
    return "\n".join(lines)


def get_voice_summary(metrics: Optional[Dict[str, Any]] = None) -> str:
    """Generate a concise voice-friendly summary of the system state for TTS."""
    if metrics is None:
        metrics = get_system_metrics()

    cpu_pct = int(round(metrics.get("cpu", {}).get("percent", 0)))
    ram_pct = int(round(metrics.get("memory", {}).get("percent", 0)))
    disk_pct = int(round(metrics.get("disk", {}).get("percent", 0)))
    status = metrics.get("analysis", {}).get("status", "NORMAL")
    return f"System Monitor started. Status is {status}. CPU is at {cpu_pct} percent, memory is at {ram_pct} percent, and disk is at {disk_pct} percent."


# ──────────────────────────────────────────────
# Extra live data used to answer questions
# ──────────────────────────────────────────────

_PROCESS_CACHE: Dict[str, Any] = {"ts": 0.0, "rows": []}
_PROCESS_CACHE_TTL = 2.0
_PROCESS_CACHE_LOCK = threading.Lock()

# How old the cached table may be before a caller insists on a fresh walk.
# The dashboard polls every 1.5s and chat answers reuse the table, so a short
# window keeps the "busiest process" name honest without re-walking ~300
# processes on every question.
_PROCESS_CACHE_MAX_STALE = 10.0

# Background sampler state. One daemon thread keeps the table warm so the first
# monitor question after a quiet period does not pay a full process walk.
_SAMPLER: Dict[str, Any] = {"thread": None, "stop": threading.Event()}
_SAMPLER_LOCK = threading.Lock()


# Windows pseudo-processes that represent idle time / kernel time, not an app.
_IDLE_PROCESS_NAMES = {"system idle process", "idle", "system"}


def _sample_processes() -> List[Dict[str, Any]]:
    """One pass over the process table ([] when psutil is unavailable).

    ``cpu_percent`` from psutil is relative to a single core (a busy threaded
    app can report 190%), so it is divided by the logical core count to give a
    share of total machine CPU.
    """
    if not psutil:
        return []
    cores = psutil.cpu_count(logical=True) or 1
    rows: List[Dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        info = getattr(proc, "info", None) or {}
        try:
            rows.append({
                "pid": int(info.get("pid") or 0),
                "name": str(info.get("name") or "unknown"),
                "cpu_percent": round(
                    min(100.0, float(info.get("cpu_percent") or 0.0) / cores), 1),
                "memory_percent": round(float(info.get("memory_percent") or 0.0), 1),
            })
        except (TypeError, ValueError):
            continue
    return rows


def _process_rows() -> List[Dict[str, Any]]:
    """Full process list with CPU/memory percentages (cached, kept warm).

    A walk of the whole process table costs ~1-2s on Windows (300+ processes),
    and psutil needs two samples before ``cpu_percent`` is a real delta rather
    than the 0% it reports on the first pass. Doing that inline made "what is my
    cpu usage?" — routed locally to answer instantly — slower than the language
    model it bypasses.

    So the table is refreshed by a background sampler thread and callers read
    whatever is cached:

      * within ``_PROCESS_CACHE_TTL``  -> fresh snapshot, no walk;
      * up to ``_PROCESS_CACHE_MAX_STALE`` old -> answered immediately and the
        sampler is nudged, because a "busiest process" name from a few seconds
        ago is far better than a multi-second stall;
      * older / empty -> one blocking walk, because there is nothing to show.

    The cache timestamp is recorded *after* the walk completes. Stamping it
    before meant a 2s walk immediately burned most of the 2s TTL, so the cache
    effectively never hit.
    """
    if not psutil:
        return []
    with _PROCESS_CACHE_LOCK:
        rows = _PROCESS_CACHE["rows"]
        age = time.time() - _PROCESS_CACHE["ts"]
    if rows and age < _PROCESS_CACHE_TTL:
        return rows
    # Something usable is cached: answer now and let the sampler refresh it.
    if rows and age < _PROCESS_CACHE_MAX_STALE:
        _ensure_process_sampler()
        return rows
    return _walk_processes()


def _walk_processes() -> List[Dict[str, Any]]:
    """Sample the process table and cache it (blocking ~1-2s)."""
    collected: List[Dict[str, Any]] = []
    try:
        collected = _sample_processes()
        # psutil reports 0% for every process on its first sample; when that
        # happens, take a second reading immediately so the values are real
        # (the delta is measured against the first pass). The check covers the
        # whole table, not just the first 50 rows — on a busy machine the busy
        # processes sit anywhere in the list, so a partial check triggered a
        # redundant second full walk on nearly every cold call.
        if collected and not any(row["cpu_percent"] for row in collected):
            collected = _sample_processes() or collected
    except Exception:  # noqa: BLE001 - the process list is best effort
        collected = []

    # Stamp on completion, so the TTL is measured from data that is actually
    # fresh rather than from the moment the walk started.
    with _PROCESS_CACHE_LOCK:
        _PROCESS_CACHE["rows"] = collected
        _PROCESS_CACHE["ts"] = time.time()
    return collected


def _sample_loop() -> None:
    """Keep the process table warm until asked to stop."""
    while not _SAMPLER["stop"].wait(_PROCESS_CACHE_TTL):
        with _PROCESS_CACHE_LOCK:
            age = time.time() - _PROCESS_CACHE["ts"]
        if age < _PROCESS_CACHE_TTL:
            continue  # somebody else refreshed it already
        try:
            _walk_processes()
        except Exception:  # noqa: BLE001 - never kill the sampler
            pass


def _ensure_process_sampler() -> None:
    """Start the warm sampler on first use (idempotent, never raises)."""
    with _SAMPLER_LOCK:
        thread = _SAMPLER["thread"]
        if thread is not None and thread.is_alive():
            return
        _SAMPLER["stop"] = threading.Event()
        try:
            _SAMPLER["thread"] = threading.Thread(
                target=_sample_loop, name="zyra-process-sampler", daemon=True
            )
            _SAMPLER["thread"].start()
        except Exception:  # noqa: BLE001 - warm cache is an optimisation
            _SAMPLER["thread"] = None


def start_process_sampler() -> None:
    """Warm the process table in the background (safe to call at startup)."""
    _ensure_process_sampler()


def stop_process_sampler() -> None:
    """Stop the warm sampler (used by tests and shutdown paths)."""
    _SAMPLER["stop"].set()


def top_processes(limit: int = 3, by: str = "cpu") -> List[Dict[str, Any]]:
    """Top ``limit`` real processes ordered by 'cpu' or 'memory'."""
    rows = _process_rows()
    if by in ("memory", "ram"):
        key = "memory_percent"
    else:
        key = "cpu_percent"
        # Idle time is not a workload — keep it out of "busiest by CPU".
        rows = [r for r in rows if r["name"].lower() not in _IDLE_PROCESS_NAMES]
    return sorted(rows, key=lambda r: r.get(key, 0.0), reverse=True)[:limit]


def disk_partition_usage() -> List[Dict[str, Any]]:
    """Per-partition usage, fullest first (unreadable drives are skipped)."""
    if not psutil:
        return []
    try:
        partitions = psutil.disk_partitions(all=False)
    except Exception:  # noqa: BLE001 - best effort
        return []
    rows: List[Dict[str, Any]] = []
    for part in partitions:
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except Exception:  # noqa: BLE001 - detached/denied drive
            continue
        rows.append({
            "device": getattr(part, "device", ""),
            "mountpoint": getattr(part, "mountpoint", ""),
            "fstype": getattr(part, "fstype", ""),
            "percent": round(float(usage.percent), 1),
            "used_str": format_bytes(usage.used),
            "free_str": format_bytes(usage.free),
            "total_str": format_bytes(usage.total),
        })
    rows.sort(key=lambda r: r["percent"], reverse=True)
    return rows


def network_identity() -> Dict[str, str]:
    """Hostname and primary IPv4 address, without contacting any server."""
    primary = ""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # A UDP "connect" only selects the outbound route; no packet is sent.
            probe.connect(("8.8.8.8", 80))
            primary = probe.getsockname()[0]
        finally:
            probe.close()
    except Exception:  # noqa: BLE001 - offline / no route
        primary = ""
    interfaces: List[str] = []
    if psutil and hasattr(psutil, "net_if_addrs"):
        try:
            for name, addrs in (psutil.net_if_addrs() or {}).items():
                for addr in addrs or []:
                    if getattr(addr, "family", None) == socket.AF_INET \
                            and not str(addr.address).startswith("127."):
                        interfaces.append(f"{name} {addr.address}")
        except Exception:  # noqa: BLE001 - best effort
            interfaces = []
    return {
        "hostname": socket.gethostname(),
        "primary_ip": primary,
        "interfaces": ", ".join(interfaces),
    }


def temperature_reading() -> Dict[str, Any]:
    """CPU temperature when the platform exposes it.

    Linux/macOS can report sensors through psutil; Windows needs vendor tools,
    so ZYRA says so honestly instead of inventing a number.
    """
    if psutil and hasattr(psutil, "sensors_temperatures"):
        try:
            sensors = psutil.sensors_temperatures() or {}
        except Exception:  # noqa: BLE001 - unsupported sensor backend
            sensors = {}
        for name, entries in sensors.items():
            for entry in entries or []:
                current = getattr(entry, "current", None)
                if current:
                    label = getattr(entry, "label", "") or name
                    return {"available": True, "label": label,
                            "celsius": round(float(current), 1)}
    return {
        "available": False,
        "reason": f"{platform.system()} does not expose CPU temperature sensors "
                  "to applications",
    }


def answer_system_query(text: str, metrics: Optional[Dict[str, Any]] = None) -> str:
    """Answer a machine question from live metrics — never invents numbers.

    An explicit monitor request (or an 'overall' question) returns the full
    ASCII card; every other topic returns a short, focused answer built from
    real psutil data.
    """
    topic = classify_system_query(text) or "overall"
    if metrics is None:
        metrics = get_system_metrics()

    cpu = metrics.get("cpu") or {}
    mem = metrics.get("memory") or {}
    disk = metrics.get("disk") or {}
    net = metrics.get("network") or {}
    batt = metrics.get("battery") or {}
    uptime = metrics.get("uptime") or {}
    sysinfo = metrics.get("system") or {}

    if topic == "overall":
        return format_system_monitor_text(metrics)

    if topic == "cpu":
        answer = (f"CPU is at {int(round(cpu.get('percent', 0.0)))}% right now "
                  f"({cpu.get('cores_physical', 1)} physical / "
                  f"{cpu.get('cores_logical', 1)} logical cores)")
        heaviest = top_processes(1, by="cpu")
        if heaviest and heaviest[0]["cpu_percent"] > 0:
            answer += (f", busiest process: {heaviest[0]['name']} "
                       f"at {heaviest[0]['cpu_percent']}%")
        return answer + "."

    if topic == "ram":
        answer = (f"Memory is at {int(round(mem.get('percent', 0.0)))}% — "
                  f"{mem.get('used_str', '0 GB')} of {mem.get('total_str', '0 GB')} "
                  f"in use, {mem.get('available_str', '0 GB')} available")
        heaviest = top_processes(1, by="memory")
        if heaviest and heaviest[0]["memory_percent"] > 0:
            answer += (f", biggest consumer: {heaviest[0]['name']} "
                       f"at {heaviest[0]['memory_percent']}%")
        return answer + "."

    if topic == "disk":
        parts = [p for p in disk_partition_usage() if p.get("mountpoint")]
        if len(parts) > 1:
            worst = parts[0]
            return (f"Primary disk is {int(round(disk.get('percent', 0.0)))}% full "
                    f"({disk.get('used_str', '0 GB')} of {disk.get('total_str', '0 GB')}); "
                    f"fullest drive is {worst['mountpoint']} at "
                    f"{int(round(worst['percent']))}% with {worst['free_str']} free.")
        return (f"Disk is {int(round(disk.get('percent', 0.0)))}% full — "
                f"{disk.get('used_str', '0 GB')} used, {disk.get('free_str', '0 GB')} free "
                f"of {disk.get('total_str', '0 GB')}.")

    if topic == "network":
        identity = network_identity()
        answer = (f"Right now {net.get('download_speed_str', '0 B/s')} down and "
                  f"{net.get('upload_speed_str', '0 B/s')} up; since boot "
                  f"{net.get('total_recv_str', '0 B')} received and "
                  f"{net.get('total_sent_str', '0 B')} sent")
        if identity.get("primary_ip"):
            answer += (f". This machine's IP is {identity['primary_ip']} "
                       f"({identity['hostname']})")
        return answer + "."

    if topic == "battery":
        if not batt.get("has_battery"):
            return ("This device reports no battery, so it is running on AC power "
                    "(no battery data is available).")
        state = "charging" if batt.get("charging") else "running on battery"
        return f"Battery is at {batt.get('percent_str', 'N/A')} and {state}."

    if topic == "uptime":
        seconds = int(uptime.get("seconds", 0) or 0)
        if seconds <= 0:
            return "I couldn't read this machine's boot time."
        boot = datetime.fromtimestamp(time.time() - seconds).strftime("%Y-%m-%d %H:%M")
        return (f"The system has been up for {uptime.get('formatted', '0h 00m')} "
                f"(since {boot}).")

    if topic == "processes":
        if not _process_rows():
            return "I can't read the process list on this system."
        by_cpu = top_processes(3, by="cpu")
        by_mem = top_processes(3, by="memory")
        return ("Busiest by CPU: "
                + ", ".join(f"{r['name']} {r['cpu_percent']}%" for r in by_cpu)
                + ". Busiest by memory: "
                + ", ".join(f"{r['name']} {r['memory_percent']}%" for r in by_mem) + ".")

    if topic == "temperature":
        reading = temperature_reading()
        if reading.get("available"):
            return (f"CPU temperature is {reading['celsius']}°C "
                    f"({reading.get('label', 'sensor')}).")
        return (f"I can't read temperature sensors here — {reading.get('reason')}. "
                "A vendor hardware-monitoring tool is needed for that.")

    if topic == "system":
        return (f"You're on {sysinfo.get('formatted') or sysinfo.get('os', 'an unknown OS')}, "
                f"host {sysinfo.get('hostname', 'unknown')}, with "
                f"{cpu.get('cores_physical', 1)} physical / {cpu.get('cores_logical', 1)} "
                f"logical cores and {mem.get('total_str', '0 GB')} of RAM. "
                f"Uptime: {uptime.get('formatted', '0h 00m')}.")

    return format_system_monitor_text(metrics)


def start_system_monitor() -> str:
    """Action invoked when System Monitor is triggered."""
    metrics = get_system_metrics()
    formatted = format_system_monitor_text(metrics)
    return formatted


if __name__ == "__main__":
    # Force UTF-8 so the progress-bar glyphs can't crash a cp1252 console.
    for _stream in (sys.stdout, sys.stderr):
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    print(format_system_monitor_text())
    print()
    for _question in (
        "what is my cpu usage",
        "how much ram is being used",
        "is my disk full",
        "check my battery",
        "how long has my pc been on",
        "what processes are using the most memory",
    ):
        print(f"Q: {_question}\nA: {answer_system_query(_question)}\n")
