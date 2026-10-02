'''Native PySide6 desktop presentation layer for the existing ZYRA engines.

This module deliberately contains UI/workflow code only. URL analysis, Nmap,
AI, TTS and history continue to be provided by the existing ZYRA modules.
'''
from __future__ import annotations
import os
import sys
import threading
import time
from typing import Any, Callable
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from backend.nmap_service import SCAN_OPERATIONS, nmap_available, run_scan, validate_target
from backend.url_analyzer import get_history, get_scan_state, start_scan
from backend.zyra_bridge import process_chat, speak_text
class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.operation = operation
        self.args = args
        self.kwargs = kwargs
    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.operation(*self.args, **self.kwargs))
        except Exception as exc:  # UI receives a safe message, not a traceback.
            self.failed.emit(str(exc))

class Card(QFrame):
    def __init__(self, title: str, value: str = "—", accent: str = "#38bdf8"):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 15, 18, 15)
        caption = QLabel(title.upper())
        caption.setObjectName("cardCaption")
        self.value = QLabel(value)
        self.value.setObjectName("cardValue")
        self.value.setStyleSheet(f"color: {accent};")
        layout.addWidget(caption)
        layout.addWidget(self.value)

class ZyraWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ZYRA — Cybersecurity Assistant")
        self.resize(1280, 820)
        self.setMinimumSize(1020, 680)
        self._threads: list[QThread] = []
        self.pages = QStackedWidget()
        self.nav = QListWidget()
        self.status = QLabel("● SYSTEM READY")
        self.module_title = QLabel("Security overview")
        self._build_ui()
        self._show_page(0)

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(245)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 25, 20, 20)
        brand = QLabel("ZYRA")
        brand.setObjectName("brand")
        subtitle = QLabel("CYBERSECURITY ASSISTANT")
        subtitle.setObjectName("subtitle")
        side.addWidget(brand)
        side.addWidget(subtitle)
        side.addSpacing(28)
        self.nav.addItems(["◈  Dashboard", "⌕  URL Analyzer", "⌁  Network Scanner", "✦  AI Assistant", "▤  Scan History", "⚙  Settings"])
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self._show_page)
        side.addWidget(self.nav, 1)
        side.addWidget(QLabel("LOCAL-FIRST SECURITY\nSafe analysis with transparent findings"), 0)
        root_layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 24, 28, 24)
        header = QHBoxLayout()
        self.module_title.setObjectName("moduleTitle")
        header.addWidget(self.module_title)
        header.addStretch()
        self.status.setObjectName("status")
        header.addWidget(self.status)
        content_layout.addLayout(header)
        content_layout.addWidget(self.pages, 1)
        root_layout.addWidget(content, 1)

        self.pages.addWidget(self._dashboard_page())
        self.pages.addWidget(self._url_page())
        self.pages.addWidget(self._nmap_page())
        self.pages.addWidget(self._assistant_page())
        self.pages.addWidget(self._history_page())
        self.pages.addWidget(self._settings_page())

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(18)
        return page, layout
    def _dashboard_page(self) -> QWidget:
        page, layout = self._page()
        intro = QLabel("Monitor threats, investigate URLs, and inspect your network from one professional workspace.")
        intro.setObjectName("muted")
        layout.addWidget(intro)
        grid = QGridLayout()
        self.url_card = Card("URL intelligence", "READY", "#38bdf8")
        self.nmap_card = Card("Nmap status", "CHECKING", "#a78bfa")
        self.history_card = Card("Recent scans", "—", "#34d399")
        grid.addWidget(self.url_card, 0, 0)
        grid.addWidget(self.nmap_card, 0, 1)
        grid.addWidget(self.history_card, 0, 2)
        layout.addLayout(grid)
        panel = QFrame(); panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        title = QLabel("Quick actions"); title.setObjectName("sectionTitle"); pl.addWidget(title)
        actions = QHBoxLayout()
        for text, row in (("Analyze a URL", 1), ("Scan a network", 2), ("Ask ZYRA AI", 3)):
            button = QPushButton(text); button.clicked.connect(lambda _, r=row: self._show_page(r)); actions.addWidget(button)
        pl.addLayout(actions)
        layout.addWidget(panel)
        layout.addStretch()
        self._refresh_dashboard()
        return page
    def _url_page(self) -> QWidget:
        page, layout = self._page()
        top = QHBoxLayout()
        self.url_input = QLineEdit(); self.url_input.setPlaceholderText("Enter a URL, e.g. https://example.com/login")
        button = QPushButton("Analyze URL"); button.clicked.connect(self._start_url)
        top.addWidget(self.url_input, 1); top.addWidget(button)
        layout.addLayout(top)
        self.url_progress = QProgressBar(); self.url_progress.setValue(0); self.url_progress.setVisible(False); layout.addWidget(self.url_progress)
        self.url_stage = QLabel("Waiting for a URL analysis."); self.url_stage.setObjectName("muted"); layout.addWidget(self.url_stage)
        result = QFrame(); result.setObjectName("panel"); rl = QVBoxLayout(result)
        self.url_summary = QLabel("No analysis yet"); self.url_summary.setObjectName("resultHeadline"); rl.addWidget(self.url_summary)
        self.url_details = QTextEdit(); self.url_details.setReadOnly(True); rl.addWidget(self.url_details)
        layout.addWidget(result, 1)
        return page
    def _nmap_page(self) -> QWidget:
        page, layout = self._page()
        row = QHBoxLayout()
        self.scan_target = QLineEdit("127.0.0.1"); self.scan_target.setPlaceholderText("Target IP, CIDR range, or hostname")
        self.scan_operation = QComboBox()
        for key, meta in SCAN_OPERATIONS.items(): self.scan_operation.addItem(meta["label"], key)
        self.scan_ports = QLineEdit(); self.scan_ports.setPlaceholderText("Ports (optional, e.g. 80,443)")
        scan_button = QPushButton("Start scan"); scan_button.clicked.connect(self._start_nmap)
        row.addWidget(self.scan_target, 2); row.addWidget(self.scan_operation, 2); row.addWidget(self.scan_ports, 2); row.addWidget(scan_button)
        layout.addLayout(row)
        self.nmap_progress = QProgressBar(); self.nmap_progress.setVisible(False); layout.addWidget(self.nmap_progress)
        self.nmap_status = QLabel("Nmap scans run in a background worker."); self.nmap_status.setObjectName("muted"); layout.addWidget(self.nmap_status)
        self.nmap_table = QTableWidget(0, 5); self.nmap_table.setHorizontalHeaderLabels(["Host", "Port", "Protocol", "Service", "State"]); self.nmap_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.nmap_table, 1)
        return page
    def _assistant_page(self) -> QWidget:
        page, layout = self._page()
        self.chat_log = QTextEdit(); self.chat_log.setReadOnly(True); self.chat_log.setPlaceholderText("ZYRA responses will appear here…"); layout.addWidget(self.chat_log, 1)
        row = QHBoxLayout(); self.chat_input = QLineEdit(); self.chat_input.setPlaceholderText("Ask a cybersecurity question or request an explanation…"); self.chat_input.returnPressed.connect(self._ask_ai)
        ask = QPushButton("Send"); ask.clicked.connect(self._ask_ai); speak = QPushButton("Speak last reply"); speak.clicked.connect(self._speak_last)
        row.addWidget(self.chat_input, 1); row.addWidget(ask); row.addWidget(speak); layout.addLayout(row)
        self.last_reply = ""
        return page
    def _history_page(self) -> QWidget:
        page, layout = self._page(); self.history_list = QListWidget(); layout.addWidget(self.history_list, 1)
        refresh = QPushButton("Refresh history"); refresh.clicked.connect(self._refresh_history); layout.addWidget(refresh); self._refresh_history(); return page
    def _settings_page(self) -> QWidget:
        page, layout = self._page(); info = QFrame(); info.setObjectName("panel"); il = QVBoxLayout(info)
        section = QLabel("Configuration")
        section.setObjectName("sectionTitle")
        il.addWidget(section)
        il.addWidget(QLabel("Secrets remain outside the source code and are read from environment variables."))
        for label, env in (("VirusTotal", "VIRUSTOTAL_API_KEY"), ("Ollama host", "ZYRA_OLLAMA_HOST"), ("Ollama model", "ZYRA_OLLAMA_MODEL"), ("Voice", "ZYRA_TTS_VOICE")):
            value = "Configured" if os.environ.get(env) else "Not configured / default"
            line = QLabel(f"{label}:  {value}   ({env})"); line.setObjectName("settingLine"); il.addWidget(line)
        il.addWidget(QLabel("Nmap must be installed separately and available on PATH."))
        layout.addWidget(info); layout.addStretch(); return page
    def _show_page(self, index: int) -> None:
        if index < 0 or index >= self.pages.count(): return
        self.pages.setCurrentIndex(index)
        titles = ["Security overview", "URL Analyzer", "Network Scanner", "AI Security Assistant", "Scan History", "Settings"]
        self.module_title.setText(titles[index])
        if index == 0: self._refresh_dashboard()

    def _run_worker(self, operation: Callable[..., Any], done: Callable[[Any], None], *args: Any, **kwargs: Any) -> None:
        thread = QThread(self); worker = Worker(operation, *args, **kwargs); worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.finished.connect(done); worker.failed.connect(self._show_error)
        worker.finished.connect(thread.quit); worker.failed.connect(thread.quit); thread.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater)
        self._threads.append(thread); thread.finished.connect(lambda: self._threads.remove(thread) if thread in self._threads else None); thread.start()

    def _start_url(self) -> None:
        url = self.url_input.text().strip()
        if not url: self._show_error("Enter a URL before starting the analysis."); return
        self.url_progress.setVisible(True); self.url_progress.setValue(5); self.url_stage.setText("Starting secure URL analysis…"); self.status.setText("● ANALYSIS RUNNING")
        launch = start_scan(url, source="desktop")
        if not launch.get("success"): self._show_error(launch.get("error", "Unable to start URL analysis.")); return
        self._run_worker(self._poll_url, self._finish_url, launch["scan_id"])

    @staticmethod
    def _poll_url(scan_id: str) -> dict:
        deadline = time.time() + 120
        while time.time() < deadline:
            state = get_scan_state(scan_id)
            if state and str(state.get("status", "")).upper() in ("COMPLETE", "ERROR"): return state
            time.sleep(0.35)
        return {"status": "ERROR", "error": "The analysis timed out. Please try again."}

    def _finish_url(self, state: dict) -> None:
        self.url_progress.setValue(int(state.get("progress", 100))); self.url_progress.setVisible(False); self.status.setText("● SYSTEM READY")
        if str(state.get("status")).upper() != "COMPLETE": self._show_error(state.get("error", "URL analysis failed.")); return
        result = state.get("result", {}); score = result.get("score", "—"); risk = result.get("risk_level_label", result.get("classification_label", "UNKNOWN"))
        self.url_summary.setText(f"{risk}  •  Safety score {score}/100  •  {result.get('domain_display', result.get('hostname', 'unknown'))}")
        findings = result.get("findings") or result.get("reasoning") or result.get("recommendation") or "No additional findings."
        if isinstance(findings, list): findings = "\n".join(f"• {item}" for item in findings)
        self.url_details.setPlainText(str(findings)); self._refresh_history(); self._refresh_dashboard()

    def _start_nmap(self) -> None:
        target = self.scan_target.text().strip(); valid, message = validate_target(target)
        if not valid: self._show_error(message); return
        operation = self.scan_operation.currentData(); self.nmap_progress.setVisible(True); self.nmap_progress.setRange(0, 0); self.nmap_status.setText("Nmap scan running in the background…"); self.status.setText("● NETWORK SCAN RUNNING")
        self._run_worker(run_scan, self._finish_nmap, operation, target, self.scan_ports.text().strip() or None, request_text="Desktop scan")

    def _finish_nmap(self, result: dict) -> None:
        self.nmap_progress.setVisible(False); self.status.setText("● SYSTEM READY")
        if not result.get("success"): self._show_error(result.get("error", "Nmap scan failed.")); return
        self.nmap_status.setText(f"Completed: {result.get('hosts_count', 0)} host(s), {result.get('open_ports_count', 0)} open port(s). Verdict: {result.get('analysis', {}).get('verdict', 'Unknown')}")
        rows = []
        for host in result.get("hosts", []):
            for port in host.get("ports", []): rows.append((host.get("ip", ""), port.get("port", ""), port.get("protocol", ""), port.get("service", ""), port.get("state", "")))
        self.nmap_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row): self.nmap_table.setItem(r, c, QTableWidgetItem(str(value)))

    def _ask_ai(self) -> None:
        message = self.chat_input.text().strip()
        if not message: return
        self.chat_input.clear(); self.chat_log.append(f"<b>You</b><br>{message}<br>"); self.status.setText("● ZYRA THINKING…"); self._run_worker(process_chat, self._finish_ai, message)

    def _finish_ai(self, reply: str) -> None:
        self.last_reply = str(reply); self.chat_log.append(f"<b>ZYRA</b><br>{self.last_reply}<br>"); self.status.setText("● SYSTEM READY")

    def _speak_last(self) -> None:
        if self.last_reply: speak_text(self.last_reply)

    def _refresh_history(self) -> None:
        if not hasattr(self, "history_list"): return
        self.history_list.clear()
        for entry in get_history(25):
            self.history_list.addItem(f"{entry.get('timestamp_display', 'Unknown time')}  •  {entry.get('domain', entry.get('url', 'Unknown'))}  •  {entry.get('risk_level_label', entry.get('classification_label', 'UNKNOWN'))}  •  score {entry.get('score', '—')}")

    def _refresh_dashboard(self) -> None:
        if not hasattr(self, "url_card"): return
        self.history_card.value.setText(str(len(get_history(25))))
        state = nmap_available(); self.nmap_card.value.setText(state.get("version", "UNAVAILABLE") if state.get("available") else "UNAVAILABLE")

    def _show_error(self, message: str) -> None:
        self.status.setText("● READY — ACTION NEEDED")
        QMessageBox.warning(self, "ZYRA", str(message))


def run_desktop() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("ZYRA")
    window = ZyraWindow(); window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(run_desktop())
