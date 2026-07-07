"""
EdgeIQ Desktop — main QMainWindow with tabbed layout.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import APP_NAME, APP_SUBTITLE, APP_VERSION
from repository.database import initialize_database
from gui.styles import APP_STYLESHEET, ACCENT, BG, MUTED, TEXT
from gui.tabs.dashboard_tab import DashboardTab
from gui.tabs.bets_tab import BetsTab
from gui.tabs.analysis_tab import AnalysisTab
from gui.tabs.entries_tab import EntriesTab


class EdgeIQWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        initialize_database()
        self.setWindowTitle(f"{APP_NAME}  ·  {APP_SUBTITLE}")
        self.setMinimumSize(1100, 720)
        self.resize(1280, 800)

        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(
            f"background-color: {BG};"
            f"border-bottom: 1px solid #2e3247;"
        )
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 0, 24, 0)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title_row = QLabel(
            f'<span style="font-size:17px; font-weight:700; color:{TEXT};">'
            f'{APP_NAME}</span>'
            f'<span style="font-size:13px; color:{MUTED};"> &nbsp;{APP_SUBTITLE}'
            f'&nbsp;&nbsp;·&nbsp;&nbsp;{APP_VERSION}</span>'
        )
        title_row.setTextFormat(Qt.TextFormat.RichText)
        header_layout.addWidget(title_row)
        root.addWidget(header)

        # ── Tab widget ────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._dashboard_tab = DashboardTab()
        self._bets_tab      = BetsTab()
        self._analysis_tab  = AnalysisTab()
        self._entries_tab   = EntriesTab()

        self._tabs.addTab(self._dashboard_tab, "  📊  Dashboard  ")
        self._tabs.addTab(self._bets_tab,      "  🎰  Track Bets  ")
        self._tabs.addTab(self._analysis_tab,  "  🔍  Analysis  ")
        self._tabs.addTab(self._entries_tab,   "  🧾  Entries  ")

        root.addWidget(self._tabs)

        # ── Wire cross-tab signals ────────────────────────────────────────────
        # Refresh dashboard stats whenever a new bet is saved
        self._bets_tab.bet_saved.connect(self._dashboard_tab.refresh_stats)

        # ── Status bar ────────────────────────────────────────────────────────
        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage(f"{APP_NAME} {APP_VERSION}  ·  Ready")
