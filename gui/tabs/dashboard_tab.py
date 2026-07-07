"""
Dashboard tab — betting stats overview + Top 25 props (PrizePicks / Underdog / Both).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import data.providers.prizepicks as _pp
import data.providers.underdog as _ud
from data.providers.injury_feed import fetch_all_injuries
from services.dashboard import get_dashboard, get_starting_bankroll, set_starting_bankroll
from gui.styles import ACCENT, BORDER, GREEN, MUTED, RED, SURFACE, SURFACE2, TEXT, YELLOW, CYAN
from utils.logging import get_logger

logger = get_logger(__name__)

# Platform display name → normalized key used in fetcher
_PLATFORMS = {
    "PrizePicks": "prizepicks",
    "Underdog":   "underdog",
    "Both":       "both",
}

# Accent colors per platform badge
_PLATFORM_COLORS = {
    "PrizePicks": "#7c5cd8",
    "Underdog":   "#f59e0b",
}


# ── Background worker ─────────────────────────────────────────────────────────

class _PropFetcher(QThread):
    """Fetches props from one or both platforms off the main thread."""

    finished = pyqtSignal(list)
    error    = pyqtSignal(str)

    def __init__(self, platform: str, sport: str | None, parent=None):
        super().__init__(parent)
        self.platform = platform   # "prizepicks" | "underdog" | "both"
        self.sport    = sport

    def run(self):
        try:
            props = self._fetch()
            self.finished.emit(props)
        except Exception as e:
            logger.exception("Failed to fetch dashboard props")
            self.error.emit(str(e))

    def _fetch(self) -> list[dict]:
        sport = self.sport or None
        n     = 25

        if self.platform == "prizepicks":
            props = _pp.top_props(n=n, sport=sport)
            for p in props:
                p.setdefault("platform", "PrizePicks")
            return props

        if self.platform == "underdog":
            return _ud.top_props(n=n, sport=sport)

        # Both — fetch in parallel using threads isn't needed here since we're
        # already off the main thread; fetch sequentially then merge & re-rank.
        pp_props = _pp.fetch_projections()
        ud_props = _ud.fetch_projections()

        for p in pp_props:
            p.setdefault("platform", "PrizePicks")

        combined = pp_props + ud_props

        if sport:
            combined = [p for p in combined if p["league"] == sport.upper()]

        combined.sort(key=lambda p: p["trending_count"], reverse=True)
        return combined[:n]


# ── Injury fetcher ────────────────────────────────────────────────────────────

class _InjuryFetcher(QThread):
    finished = pyqtSignal(list)

    def run(self):
        try:
            self.finished.emit(fetch_all_injuries())
        except Exception:
            logger.exception("Failed to fetch injuries")
            self.finished.emit([])


# ── Stat card widget ──────────────────────────────────────────────────────────

class _StatCard(QFrame):
    def __init__(self, label: str, value: str, color: str = ACCENT, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        self._value_label = QLabel(value)
        self._value_label.setObjectName("stat-value")
        self._value_label.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: 700;")

        lbl = QLabel(label)
        lbl.setObjectName("stat-label")

        layout.addWidget(self._value_label)
        layout.addWidget(lbl)

    def set_value(self, value: str):
        self._value_label.setText(value)


# ── Bankroll card — editable ──────────────────────────────────────────────────

class _BankrollCard(QFrame):
    """Stat card for the starting bankroll with an inline ✎ edit button."""

    changed = pyqtSignal(float)   # emitted after the user saves a new value

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 10, 12, 10)
        outer.setSpacing(2)

        # Top row: value + edit button
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self._value_label = QLabel("—")
        self._value_label.setStyleSheet(
            f"color: {ACCENT}; font-size: 24px; font-weight: 700;"
        )
        top_row.addWidget(self._value_label)
        top_row.addStretch()

        self._edit_btn = QPushButton("✎")
        self._edit_btn.setFixedSize(24, 24)
        self._edit_btn.setToolTip("Edit starting bankroll")
        self._edit_btn.setStyleSheet(
            f"QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER};"
            f" border-radius: 4px; color: {MUTED}; font-size: 13px; padding: 0; }}"
            f"QPushButton:hover {{ color: {TEXT}; border-color: {ACCENT}; }}"
        )
        self._edit_btn.clicked.connect(self._open_editor)
        top_row.addWidget(self._edit_btn, alignment=Qt.AlignmentFlag.AlignTop)

        outer.addLayout(top_row)

        lbl = QLabel("Bankroll")
        lbl.setObjectName("stat-label")
        outer.addWidget(lbl)

    def set_value(self, value: str):
        self._value_label.setText(value)

    def _open_editor(self):
        current = get_starting_bankroll()
        dlg = _BankrollDialog(current, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_amount = dlg.value()
            set_starting_bankroll(new_amount)
            self.changed.emit(new_amount)


# ── Bankroll edit dialog ──────────────────────────────────────────────────────

class _BankrollDialog(QDialog):

    def __init__(self, current: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Starting Bankroll")
        self.setFixedWidth(300)
        self.setStyleSheet(parent.window().styleSheet() if parent else "")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl = QLabel("Starting Bankroll")
        lbl.setObjectName("stat-label")
        layout.addWidget(lbl)

        self._spin = QDoubleSpinBox()
        self._spin.setRange(0.01, 10_000_000)
        self._spin.setDecimals(2)
        self._spin.setPrefix("$ ")
        self._spin.setValue(current)
        self._spin.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(self._spin)

        hint = QLabel("This is the bankroll amount your profit & ROI are calculated against.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> float:
        return self._spin.value()


# ── Main tab ──────────────────────────────────────────────────────────────────

class DashboardTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fetcher: _PropFetcher | None = None
        self._injury_fetcher: _InjuryFetcher | None = None
        self._build_ui()
        self._load_stats()
        self._load_injuries()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # Injury alert banner (hidden until injuries load)
        self._injury_banner = QFrame()
        self._injury_banner.setStyleSheet(
            f"background: #2a1a1a; border: 1px solid {RED}; border-radius: 6px; padding: 4px;"
        )
        self._injury_banner.hide()
        banner_layout = QHBoxLayout(self._injury_banner)
        banner_layout.setContentsMargins(12, 6, 12, 6)
        self._injury_label = QLabel()
        self._injury_label.setStyleSheet(f"color: {RED}; font-size: 12px;")
        self._injury_label.setWordWrap(True)
        banner_layout.addWidget(self._injury_label)
        root.addWidget(self._injury_banner)

        # Section: Betting Stats
        stats_title = QLabel("Betting Overview")
        stats_title.setObjectName("section-title")
        root.addWidget(stats_title)

        # Row 1 — main stat cards
        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(12)

        self._card_record   = _StatCard("Record",        "—")
        self._card_winpct   = _StatCard("Win %",         "—", YELLOW)
        self._card_profit   = _StatCard("Net Profit",    "—", GREEN)
        self._card_roi      = _StatCard("ROI",           "—", ACCENT)
        self._card_wagered  = _StatCard("Total Wagered", "—", MUTED)
        self._card_bankroll = _BankrollCard()
        self._card_bankroll.changed.connect(self._load_stats)

        for card in (
            self._card_record, self._card_winpct, self._card_profit,
            self._card_roi, self._card_wagered, self._card_bankroll,
        ):
            self._cards_row.addWidget(card)

        root.addLayout(self._cards_row)

        # Row 2 — streak / drawdown cards
        self._streak_row = QHBoxLayout()
        self._streak_row.setSpacing(12)

        self._card_streak   = _StatCard("Current Streak", "—", ACCENT)
        self._card_best     = _StatCard("Best Streak",    "—", GREEN)
        self._card_worst    = _StatCard("Worst Streak",   "—", RED)
        self._card_drawdown = _StatCard("Max Drawdown",   "—", YELLOW)
        self._card_pushes   = _StatCard("Pushes",         "—", MUTED)

        for card in (
            self._card_streak, self._card_best, self._card_worst,
            self._card_drawdown, self._card_pushes,
        ):
            self._streak_row.addWidget(card)

        root.addLayout(self._streak_row)

        # Divider
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        # Section: Top 25 Props header row
        props_header = QHBoxLayout()
        props_header.setSpacing(8)

        self._props_title = QLabel("Top 25 Props")
        self._props_title.setObjectName("section-title")
        props_header.addWidget(self._props_title)

        props_header.addStretch()

        self._platform_filter = QComboBox()
        self._platform_filter.addItems(list(_PLATFORMS.keys()))   # PrizePicks / Underdog / Both
        self._platform_filter.setFixedWidth(130)
        self._platform_filter.currentIndexChanged.connect(self._on_filter_changed)
        props_header.addWidget(self._platform_filter)

        self._sport_filter = QComboBox()
        self._sport_filter.addItems(["All Sports", "NBA", "WNBA", "NFL", "MLB"])
        self._sport_filter.setFixedWidth(120)
        self._sport_filter.currentIndexChanged.connect(self._on_filter_changed)
        props_header.addWidget(self._sport_filter)

        self._refresh_btn = QPushButton("⟳  Refresh")
        self._refresh_btn.setFixedWidth(110)
        self._refresh_btn.clicked.connect(self._load_props)
        props_header.addWidget(self._refresh_btn)

        root.addLayout(props_header)

        self._status_label = QLabel("Loading props…")
        self._status_label.setObjectName("muted")
        root.addWidget(self._status_label)

        # Props table — 8 columns now (added Platform)
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels(
            ["#", "Platform", "Player", "Sport", "Stat", "Line", "Game", "🔥 Trending"]
        )
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        root.addWidget(self._table)

        self._load_props()

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_stats(self):
        """Load betting stats from DB."""
        try:
            stats = get_dashboard()
            total   = stats["wins"] + stats["losses"]
            win_pct = (stats["wins"] / total * 100) if total else 0
            profit  = stats["profit"]

            self._card_record.set_value(stats["record"])
            self._card_winpct.set_value(f"{win_pct:.1f}%")
            self._card_profit.set_value(f"${profit:.2f}")
            color = GREEN if profit >= 0 else RED
            self._card_profit._value_label.setStyleSheet(
                f"color: {color}; font-size: 24px; font-weight: 700;"
            )
            self._card_roi.set_value(f"{stats['roi']:.1f}%")
            self._card_wagered.set_value(f"${stats['wagered']:.2f}")
            self._card_bankroll.set_value(f"${stats['bankroll']:.2f}")

            # Streak / drawdown row
            streak = stats.get("current_streak", 0)
            streak_str = f"W{streak}" if streak > 0 else (f"L{abs(streak)}" if streak < 0 else "—")
            streak_color = GREEN if streak > 0 else (RED if streak < 0 else MUTED)
            self._card_streak._value_label.setText(streak_str)
            self._card_streak._value_label.setStyleSheet(
                f"color: {streak_color}; font-size: 24px; font-weight: 700;"
            )
            best = stats.get("best_streak", 0)
            self._card_best.set_value(f"W{best}" if best else "—")
            worst = stats.get("worst_streak", 0)
            self._card_worst.set_value(f"L{abs(worst)}" if worst else "—")
            self._card_drawdown.set_value(f"${stats.get('max_drawdown', 0):.2f}")
            self._card_pushes.set_value(str(stats.get("pushes", 0)))
        except KeyError as e:
            logger.warning("Dashboard stats missing expected key: %s", e)
            if hasattr(self, "_status_label"):
                self._status_label.setText("Dashboard stats are incomplete.")
        except Exception as e:
            logger.exception("Failed to load dashboard stats")
            if hasattr(self, "_status_label"):
                self._status_label.setText(f"Dashboard stats unavailable: {e}")

    def _load_injuries(self):
        """Fetch injuries off the main thread and update the banner."""
        if self._injury_fetcher and self._injury_fetcher.isRunning():
            return
        self._injury_fetcher = _InjuryFetcher(parent=self)
        self._injury_fetcher.finished.connect(self._on_injuries_loaded)
        self._injury_fetcher.start()

    def _on_injuries_loaded(self, injuries: list):
        critical = [
            i for i in injuries
            if "Out" in i["status"] or "Doubtful" in i["status"]
        ]
        if critical:
            lines = [f"{i['player']} ({i['team']}) — {i['status']}" for i in critical[:5]]
            self._injury_label.setText("⚠  Injuries:  " + "  ·  ".join(lines))
            self._injury_banner.show()
        else:
            self._injury_banner.hide()

    def _on_filter_changed(self):
        self._load_props()

    def _load_props(self):
        """Kick off background fetch."""
        if self._fetcher and self._fetcher.isRunning():
            return

        self._refresh_btn.setEnabled(False)
        self._table.setRowCount(0)

        platform_label = self._platform_filter.currentText()
        platform_key   = _PLATFORMS[platform_label]
        sport_text     = self._sport_filter.currentText()
        sport          = None if sport_text == "All Sports" else sport_text

        self._props_title.setText(f"Top 25 Props  ·  {platform_label}")
        self._status_label.setText(f"Fetching props from {platform_label}…")

        self._fetcher = _PropFetcher(platform_key, sport, parent=self)
        self._fetcher.finished.connect(self._on_props_loaded)
        self._fetcher.error.connect(self._on_props_error)
        self._fetcher.start()

    def _on_props_loaded(self, props: list[dict]):
        self._refresh_btn.setEnabled(True)

        if not props:
            self._status_label.setText("No props available right now.")
            return

        sport_text = self._sport_filter.currentText()
        stale_props = [p for p in props if p.get("stale")]
        cache_note = ""
        if stale_props:
            max_age = max(p.get("cache_age_seconds", 0) for p in stale_props)
            cache_note = f" · cached fallback {max_age // 60}m old"

        self._status_label.setText(
            f"Showing top {len(props)} props · {sport_text} · sorted by trending{cache_note}"
        )
        self._populate_table(props)

    def _on_props_error(self, msg: str):
        self._refresh_btn.setEnabled(True)
        self._status_label.setText(f"Error: {msg}")

    def _populate_table(self, props: list[dict]):
        self._table.setRowCount(len(props))

        for row, prop in enumerate(props):
            def _item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                return item

            center = Qt.AlignmentFlag.AlignCenter

            self._table.setItem(row, 0, _item(str(row + 1), center))

            # Platform badge (colored)
            platform     = prop.get("platform", "PrizePicks")
            platform_item = _item(platform, center)
            badge_color  = _PLATFORM_COLORS.get(platform, ACCENT)
            platform_item.setForeground(QColor(badge_color))
            self._table.setItem(row, 1, platform_item)

            self._table.setItem(row, 2, _item(prop["player"]))
            self._table.setItem(row, 3, _item(prop["league"], center))
            self._table.setItem(row, 4, _item(prop["stat"]))
            self._table.setItem(row, 5, _item(
                f"{prop['line']:.1f}" if prop["line"] is not None else "—", center
            ))
            self._table.setItem(row, 6, _item(prop.get("game", ""), center))
            self._table.setItem(row, 7, _item(
                f"{prop['trending_count']:,}", center
            ))

        self._table.resizeColumnToContents(0)
        self._table.resizeColumnToContents(1)
        self._table.resizeColumnToContents(3)
        self._table.resizeColumnToContents(5)
        self._table.resizeColumnToContents(6)
        self._table.resizeColumnToContents(7)

    def refresh_stats(self):
        """Called externally after a bet is saved."""
        self._load_stats()
