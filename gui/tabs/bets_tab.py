"""
Bets tab — add a new bet and view full bet history.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
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
from services.tracker import save_bet, view_bets
from repository.bet_repository import BetRepository
from gui.styles import GREEN, RED, YELLOW


class BetsTab(QWidget):
    """Tab for adding bets and viewing bet history."""

    bet_saved = pyqtSignal()  # emitted after a new bet is saved

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_history()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(20)

        # ── Left panel: Add Bet form ──────────────────────────────────────────
        form_group = QGroupBox("Add Bet")
        form_group.setFixedWidth(320)
        form_layout = QVBoxLayout(form_group)
        form_layout.setSpacing(12)
        form_layout.setContentsMargins(16, 20, 16, 16)

        fields = QFormLayout()
        fields.setSpacing(10)
        fields.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._sport_input  = QLineEdit()
        self._sport_input.setPlaceholderText("e.g. WNBA")

        self._game_input   = QLineEdit()
        self._game_input.setPlaceholderText("e.g. NYL @ ATL")

        self._desc_input   = QLineEdit()
        self._desc_input.setPlaceholderText("e.g. Paige Bueckers Over 20.5 Pts")

        self._odds_input   = QSpinBox()
        self._odds_input.setRange(-10000, 10000)
        self._odds_input.setValue(-110)

        self._wager_input  = QDoubleSpinBox()
        self._wager_input.setRange(0.01, 100000)
        self._wager_input.setPrefix("$ ")
        self._wager_input.setDecimals(2)
        self._wager_input.setValue(10.00)

        self._result_combo = QComboBox()
        self._result_combo.addItems(["Win", "Loss", "Push"])

        fields.addRow("Sport",       self._sport_input)
        fields.addRow("Game",        self._game_input)
        fields.addRow("Description", self._desc_input)
        fields.addRow("Odds",        self._odds_input)
        fields.addRow("Wager",       self._wager_input)
        fields.addRow("Result",      self._result_combo)

        form_layout.addLayout(fields)

        self._feedback_label = QLabel("")
        self._feedback_label.setObjectName("muted")
        self._feedback_label.setWordWrap(True)
        form_layout.addWidget(self._feedback_label)

        self._save_btn = QPushButton("Save Bet")
        self._save_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._save_btn.clicked.connect(self._on_save_bet)
        form_layout.addWidget(self._save_btn)

        form_layout.addStretch()
        root.addWidget(form_group)

        # ── Right panel: Bet history ──────────────────────────────────────────
        history_layout = QVBoxLayout()
        history_layout.setSpacing(10)

        header_row = QHBoxLayout()
        title = QLabel("Bet History")
        title.setObjectName("section-title")
        header_row.addWidget(title)
        header_row.addStretch()

        self._history_count = QLabel("")
        self._history_count.setObjectName("muted")
        header_row.addWidget(self._history_count)

        history_layout.addLayout(header_row)

        self._history_table = QTableWidget()
        self._history_table.setColumnCount(7)
        self._history_table.setHorizontalHeaderLabels(
            ["Sport", "Game", "Description", "Odds", "Wager", "Result", "Profit"]
        )
        self._history_table.setAlternatingRowColors(True)
        self._history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.horizontalHeader().setStretchLastSection(False)
        self._history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        history_layout.addWidget(self._history_table)
        root.addLayout(history_layout)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_save_bet(self):
        sport  = self._sport_input.text().strip()
        game   = self._game_input.text().strip()
        desc   = self._desc_input.text().strip()
        odds   = self._odds_input.value()
        wager  = self._wager_input.value()
        result = self._result_combo.currentText()

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
        self._odds_input.setValue(-110)
        self._wager_input.setValue(10.00)
        self._result_combo.setCurrentIndex(0)

    def _show_feedback(self, msg: str, error: bool):
        color = RED if error else GREEN
        self._feedback_label.setText(msg)
        self._feedback_label.setStyleSheet(f"color: {color}; font-size: 12px;")

    # ── History table ─────────────────────────────────────────────────────────

    def _load_history(self):
        bets = BetRepository().get_all()
        self._history_table.setRowCount(len(bets))
        self._history_count.setText(f"{len(bets)} bets")

        for row, bet in enumerate(reversed(bets)):  # newest first
            def _item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                return item

            center = Qt.AlignmentFlag.AlignCenter

            self._history_table.setItem(row, 0, _item(bet.sport))
            self._history_table.setItem(row, 1, _item(bet.game))
            self._history_table.setItem(row, 2, _item(bet.description))
            self._history_table.setItem(row, 3, _item(str(bet.odds), center))
            self._history_table.setItem(row, 4, _item(f"${bet.wager:.2f}", center))

            result_item = _item(bet.result, center)
            if bet.result == "Win":
                result_item.setForeground(
                    __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(GREEN)
                )
            elif bet.result == "Loss":
                result_item.setForeground(
                    __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(RED)
                )
            self._history_table.setItem(row, 5, result_item)

            profit_item = _item(f"${bet.profit:.2f}", center)
            profit_item.setForeground(
                __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(
                    GREEN if bet.profit >= 0 else RED
                )
            )
            self._history_table.setItem(row, 6, profit_item)

        self._history_table.resizeColumnToContents(0)
        self._history_table.resizeColumnToContents(3)
        self._history_table.resizeColumnToContents(4)
        self._history_table.resizeColumnToContents(5)
        self._history_table.resizeColumnToContents(6)

    def refresh(self):
        """Called externally to reload history."""
        self._load_history()
