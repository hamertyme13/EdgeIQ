"""
Performance tab — bankroll curve chart, profit breakdowns, model calibration.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPen, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCharts import (
    QChart,
    QChartView,
    QLineSeries,
    QValueAxis,
)

from repository.bet_repository import BetRepository
from services.dashboard import get_starting_bankroll
from analytics.calibration import calibrate
from gui.styles import ACCENT, BORDER, BG, GREEN, MUTED, RED, SURFACE, SURFACE2, TEXT, YELLOW


class PerformanceTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        # ── Header ────────────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        title = QLabel("Performance Analytics")
        title.setObjectName("section-title")
        header_row.addWidget(title)
        header_row.addStretch()
        refresh_btn = QPushButton("⟳  Refresh")
        refresh_btn.setFixedWidth(110)
        refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(refresh_btn)
        root.addLayout(header_row)

        # ── Row 1: chart + calibration ─────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(16)
        row1.addWidget(self._build_chart_panel(), stretch=3)
        row1.addWidget(self._build_calibration_panel(), stretch=2)
        root.addLayout(row1)

        # ── Row 2: breakdowns ─────────────────────────────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(16)
        row2.addWidget(self._build_breakdown_panel("By Sport", "_sport_table"))
        row2.addWidget(self._build_breakdown_panel("By Stat Type", "_stat_table"))
        row2.addWidget(self._build_breakdown_panel("By Platform", "_platform_table"))
        root.addLayout(row2)

    # ── Chart panel ───────────────────────────────────────────────────────────

    def _build_chart_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        lbl = QLabel("Bankroll Curve")
        lbl.setObjectName("section-title")
        header.addWidget(lbl)
        self._chart_subtitle = QLabel("")
        self._chart_subtitle.setObjectName("muted")
        header.addStretch()
        header.addWidget(self._chart_subtitle)
        layout.addLayout(header)

        self._chart = QChart()
        self._chart.setBackgroundBrush(QColor(SURFACE))
        self._chart.setPlotAreaBackgroundBrush(QColor(SURFACE))
        self._chart.setPlotAreaBackgroundVisible(True)
        self._chart.legend().setVisible(False)
        self._chart.setMargins(__import__("PyQt6.QtCore", fromlist=["QMargins"]).QMargins(0, 0, 0, 0))

        self._chart_view = QChartView(self._chart)
        self._chart_view.setRenderHint(
            __import__("PyQt6.QtGui", fromlist=["QPainter"]).QPainter.RenderHint.Antialiasing
        )
        self._chart_view.setMinimumHeight(220)
        self._chart_view.setStyleSheet(f"background: {SURFACE}; border: none;")
        layout.addWidget(self._chart_view)

        return frame

    def _update_chart(self, bankroll_curve: list[float], starting_bankroll: float):
        self._chart.removeAllSeries()
        for ax in self._chart.axes():
            self._chart.removeAxis(ax)

        if not bankroll_curve:
            self._chart_subtitle.setText("No bets yet")
            return

        final = starting_bankroll + bankroll_curve[-1]
        self._chart_subtitle.setText(
            f"Starting ${starting_bankroll:.0f}  →  Current ${final:.2f}"
        )

        series = QLineSeries()
        color = QColor(GREEN if bankroll_curve[-1] >= 0 else RED)
        pen = QPen(color)
        pen.setWidth(2)
        series.setPen(pen)

        series.append(0, starting_bankroll)
        for i, delta in enumerate(bankroll_curve, start=1):
            series.append(i, starting_bankroll + delta)

        self._chart.addSeries(series)

        ax_x = QValueAxis()
        ax_x.setRange(0, len(bankroll_curve))
        ax_x.setLabelFormat("%d")
        ax_x.setLabelsColor(QColor(MUTED))
        ax_x.setGridLineColor(QColor(BORDER))
        ax_x.setTitleText("Bet #")
        ax_x.setTitleBrush(QColor(MUTED))

        values = [starting_bankroll + d for d in bankroll_curve]
        values.append(starting_bankroll)
        y_min = min(values) * 0.97
        y_max = max(values) * 1.03

        ax_y = QValueAxis()
        ax_y.setRange(y_min, y_max)
        ax_y.setLabelFormat("$%.0f")
        ax_y.setLabelsColor(QColor(MUTED))
        ax_y.setGridLineColor(QColor(BORDER))

        self._chart.addAxis(ax_x, Qt.AlignmentFlag.AlignBottom)
        self._chart.addAxis(ax_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(ax_x)
        series.attachAxis(ax_y)

    # ── Calibration panel ─────────────────────────────────────────────────────

    def _build_calibration_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        lbl = QLabel("Model Calibration")
        lbl.setObjectName("section-title")
        layout.addWidget(lbl)

        hint = QLabel("Predicted confidence vs actual win rate per bucket.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._cal_table = QTableWidget()
        self._cal_table.setColumnCount(5)
        self._cal_table.setHorizontalHeaderLabels(
            ["Confidence", "Bets", "Wins", "Actual %", "Error"]
        )
        self._cal_table.setAlternatingRowColors(True)
        self._cal_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._cal_table.verticalHeader().setVisible(False)
        self._cal_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._cal_table)

        return frame

    # ── Breakdown panel factory ───────────────────────────────────────────────

    def _build_breakdown_panel(self, title: str, attr: str) -> QWidget:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        lbl = QLabel(title)
        lbl.setObjectName("section-title")
        layout.addWidget(lbl)

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Group", "Bets", "Win %", "Profit", "ROI"])
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)

        setattr(self, attr, table)
        return frame

    # ── Data loading ──────────────────────────────────────────────────────────

    def refresh(self):
        repo  = BetRepository()
        stats = repo.dashboard_stats()
        bets  = repo.get_all()
        starting = get_starting_bankroll()

        self._update_chart(stats["bankroll_curve"], starting)
        self._update_breakdown(self._sport_table,    stats["by_sport"])
        self._update_breakdown(self._stat_table,     stats["by_stat"])
        self._update_breakdown(self._platform_table, stats["by_platform"])
        self._update_calibration(bets)

    def _update_breakdown(self, table: QTableWidget, groups: dict):
        rows = sorted(groups.items(), key=lambda x: x[1]["profit"], reverse=True)
        table.setRowCount(len(rows))

        def _item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
            item = QTableWidgetItem(str(text))
            item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
            return item

        center = Qt.AlignmentFlag.AlignCenter

        for row, (group, g) in enumerate(rows):
            table.setItem(row, 0, _item(group))
            table.setItem(row, 1, _item(str(g["bets"]), center))
            table.setItem(row, 2, _item(f"{g['win_pct']:.1f}%", center))

            profit_item = _item(f"${g['profit']:.2f}", center)
            profit_item.setForeground(QColor(GREEN if g["profit"] >= 0 else RED))
            table.setItem(row, 3, profit_item)

            roi_item = _item(f"{g['roi']:.1f}%", center)
            roi_item.setForeground(QColor(GREEN if g["roi"] >= 0 else RED))
            table.setItem(row, 4, roi_item)

    def _update_calibration(self, bets):
        cal_input = [
            {"win_probability": b.win_probability, "result": b.result}
            for b in bets
            if b.win_probability and b.win_probability > 0
        ]

        if not cal_input:
            self._cal_table.setRowCount(1)
            msg = QTableWidgetItem("No probability data yet — add win probabilities when tracking bets.")
            msg.setForeground(QColor(MUTED))
            self._cal_table.setItem(0, 0, msg)
            self._cal_table.setSpan(0, 0, 1, 5)
            return

        buckets = calibrate(cal_input)
        self._cal_table.setRowCount(len(buckets))

        def _item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
            item = QTableWidgetItem(str(text))
            item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
            return item

        center = Qt.AlignmentFlag.AlignCenter

        for row, b in enumerate(buckets):
            self._cal_table.setItem(row, 0, _item(b.label))
            self._cal_table.setItem(row, 1, _item(str(b.bets), center))
            self._cal_table.setItem(row, 2, _item(str(b.wins), center))
            self._cal_table.setItem(row, 3, _item(f"{b.actual_pct:.1f}%", center))

            err_item = _item(f"{b.error:+.1f}%", center)
            err_item.setForeground(QColor(GREEN if b.error >= 0 else RED))
            self._cal_table.setItem(row, 4, err_item)
