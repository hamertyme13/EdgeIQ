"""
Bets tab — add a new bet (with platform, stat type, win probability)
and view full bet history with hit-rate-by-stat breakdown.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models.bet import Bet
from services.betting import potential_profit
from services.tracker import save_bet
from repository.bet_repository import BetRepository
from gui.styles import GREEN, RED, YELLOW, MUTED, ACCENT, SURFACE, BORDER


class BetsTab(QWidget):
    """Tab for adding bets and viewing bet history with hit-rate breakdown."""

    bet_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_history()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        # ── Left: add-bet form ────────────────────────────────────────────────
        form_group = QGroupBox("Add Bet")
        form_group.setFixedWidth(340)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(16, 20, 16, 16)

        fields = QFormLayout()
        fields.setSpacing(8)
        fields.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._sport_input   = QLineEdit()
        self._sport_input.setPlaceholderText("e.g. WNBA")

        self._game_input    = QLineEdit()
        self._game_input.setPlaceholderText("e.g. NYL @ ATL")

        self._desc_input    = QLineEdit()
        self._desc_input.setPlaceholderText("e.g. Paige Bueckers Over 20.5 Pts")

        self._platform_combo = QComboBox()
        self._platform_combo.addItems(["PrizePicks", "Underdog", "Sportsbook", "Other"])

        self._stat_type_input = QLineEdit()
        self._stat_type_input.setPlaceholderText("e.g. Points, Rebounds")

        self._odds_input    = QSpinBox()
        self._odds_input.setRange(-10000, 10000)
        self._odds_input.setValue(-110)

        self._wager_input   = QDoubleSpinBox()
        self._wager_input.setRange(0.01, 100000)
        self._wager_input.setPrefix("$ ")
        self._wager_input.setDecimals(2)
        self._wager_input.setValue(10.00)

        self._win_prob_input = QDoubleSpinBox()
        self._win_prob_input.setRange(0.0, 100.0)
        self._win_prob_input.setDecimals(1)
        self._win_prob_input.setSuffix(" %")
        self._win_prob_input.setSpecialValueText("—")

        self._result_combo  = QComboBox()
        self._result_combo.addItems(["Win", "Loss", "Push"])

        fields.addRow("Sport",           self._sport_input)
        fields.addRow("Game",            self._game_input)
        fields.addRow("Description",     self._desc_input)
        fields.addRow("Platform",        self._platform_combo)
        fields.addRow("Stat Type",       self._stat_type_input)
        fields.addRow("Odds",            self._odds_input)
        fields.addRow("Wager",           self._wager_input)
        fields.addRow("Win Prob (opt)",  self._win_prob_input)
        fields.addRow("Result",          self._result_combo)

        form_layout.addLayout(fields)

        self._feedback_label = QLabel("")
        self._feedback_label.setObjectName("muted")
        self._feedback_label.setWordWrap(True)
        form_layout.addWidget(self._feedback_label)

        save_btn = QPushButton("Save Bet")
        save_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        save_btn.clicked.connect(self._on_save_bet)
        form_layout.addWidget(save_btn)
        form_layout.addStretch()
        root.addWidget(form_group)

        # ── Right: history + breakdown ────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(12)

        # History header
        hdr = QHBoxLayout()
        title = QLabel("Bet History")
        title.setObjectName("section-title")
        hdr.addWidget(title)
        hdr.addStretch()
        self._history_count = QLabel("")
        self._history_count.setObjectName("muted")
        hdr.addWidget(self._history_count)
        right.addLayout(hdr)

        self._history_table = QTableWidget()
        self._history_table.setColumnCount(9)
        self._history_table.setHorizontalHeaderLabels(
            ["Sport", "Platform", "Game", "Description", "Stat", "Odds", "Wager", "Result", "Profit"]
        )
        self._history_table.setAlternatingRowColors(True)
        self._history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        right.addWidget(self._history_table, stretch=3)

        # Hit rate by stat breakdown
        breakdown_group = QGroupBox("Hit Rate by Stat Type")
        bl = QVBoxLayout(breakdown_group)
        bl.setContentsMargins(12, 18, 12, 12)
        self._stat_breakdown_table = QTableWidget()
        self._stat_breakdown_table.setColumnCount(5)
        self._stat_breakdown_table.setHorizontalHeaderLabels(
            ["Stat", "Bets", "Win %", "Profit", "ROI"]
        )
        self._stat_breakdown_table.setAlternatingRowColors(True)
        self._stat_breakdown_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._stat_breakdown_table.verticalHeader().setVisible(False)
        self._stat_breakdown_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._stat_breakdown_table.setFixedHeight(160)
        bl.addWidget(self._stat_breakdown_table)
        right.addWidget(breakdown_group, stretch=1)

        root.addLayout(right)

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_save_bet(self):
        sport    = self._sport_input.text().strip()
        game     = self._game_input.text().strip()
        desc     = self._desc_input.text().strip()
        platform = self._platform_combo.currentText()
        stat_type= self._stat_type_input.text().strip()
        odds     = self._odds_input.value()
        wager    = self._wager_input.value()
        win_prob = self._win_prob_input.value()  # 0.0 means "not set"
        result   = self._result_combo.currentText()

        if not sport or not game or not desc:
            self._show_feedback("Please fill in Sport, Game and Description.", error=True)
            return

        if result == "Win":
            profit = potential_profit(odds, wager)
        elif result == "Loss":
            profit = -wager
        else:
            profit = 0.0

        bet = Bet(
            sport=sport,
            game=game,
            description=desc,
            odds=odds,
            wager=wager,
            result=result,
            profit=profit,
            platform=platform,
            stat_type=stat_type,
            win_probability=win_prob,
        )

        save_bet(bet)
        self._show_feedback("✓ Bet saved successfully!", error=False)
        self._clear_form()
        self._load_history()
        self.bet_saved.emit()

    def _clear_form(self):
        self._sport_input.clear()
        self._game_input.clear()
        self._desc_input.clear()
        self._stat_type_input.clear()
        self._odds_input.setValue(-110)
        self._wager_input.setValue(10.00)
        self._win_prob_input.setValue(0.0)
        self._result_combo.setCurrentIndex(0)
        self._platform_combo.setCurrentIndex(0)

    def _show_feedback(self, msg: str, error: bool):
        color = RED if error else GREEN
        self._feedback_label.setText(msg)
        self._feedback_label.setStyleSheet(f"color: {color}; font-size: 12px;")

    # ── History + breakdown ───────────────────────────────────────────────────

    def _load_history(self):
        repo  = BetRepository()
        bets  = repo.get_all()
        stats = repo.dashboard_stats()

        self._history_table.setRowCount(len(bets))
        self._history_count.setText(f"{len(bets)} bets")

        for row, bet in enumerate(reversed(bets)):
            center = Qt.AlignmentFlag.AlignCenter

            def _item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                return item

            self._history_table.setItem(row, 0, _item(bet.sport))
            self._history_table.setItem(row, 1, _item(bet.platform or "—", center))
            self._history_table.setItem(row, 2, _item(bet.game))
            self._history_table.setItem(row, 3, _item(bet.description))
            self._history_table.setItem(row, 4, _item(bet.stat_type or "—", center))
            self._history_table.setItem(row, 5, _item(str(bet.odds), center))
            self._history_table.setItem(row, 6, _item(f"${bet.wager:.2f}", center))

            result_item = _item(bet.result, center)
            result_item.setForeground(QColor(
                GREEN if bet.result == "Win" else (RED if bet.result == "Loss" else MUTED)
            ))
            self._history_table.setItem(row, 7, result_item)

            profit_item = _item(f"${bet.profit:.2f}", center)
            profit_item.setForeground(QColor(GREEN if bet.profit >= 0 else RED))
            self._history_table.setItem(row, 8, profit_item)

        for col in [0, 1, 2, 4, 5, 6, 7, 8]:
            self._history_table.resizeColumnToContents(col)

        # Stat breakdown
        by_stat = stats.get("by_stat", {})
        rows = sorted(by_stat.items(), key=lambda x: x[1]["bets"], reverse=True)
        self._stat_breakdown_table.setRowCount(len(rows))

        for row, (stat, g) in enumerate(rows):
            center = Qt.AlignmentFlag.AlignCenter

            def _item2(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                return item

            self._stat_breakdown_table.setItem(row, 0, _item2(stat))
            self._stat_breakdown_table.setItem(row, 1, _item2(str(g["bets"]), center))
            self._stat_breakdown_table.setItem(row, 2, _item2(f"{g['win_pct']:.1f}%", center))

            profit_item = _item2(f"${g['profit']:.2f}", center)
            profit_item.setForeground(QColor(GREEN if g["profit"] >= 0 else RED))
            self._stat_breakdown_table.setItem(row, 3, profit_item)

            roi_item = _item2(f"{g['roi']:.1f}%", center)
            roi_item.setForeground(QColor(GREEN if g["roi"] >= 0 else RED))
            self._stat_breakdown_table.setItem(row, 4, roi_item)

    def refresh(self):
        self._load_history()
