"""
Analysis tab — EV Calculator and single-prop analysis side by side.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from analytics.ev import expected_value, decimal_odds, sportsbook_probability
from analytics.recommendation import recommendation
from analytics.prop_metrics import calculate_edge, calculate_confidence
from models.player import Player
from models.prop import Prop
from models.stat_type import StatType
from gui.styles import ACCENT, GREEN, RED, YELLOW, SURFACE, BORDER, TEXT, MUTED


class AnalysisTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(20)

        root.addWidget(self._build_ev_panel())
        root.addWidget(self._build_prop_panel())

    # ── EV Calculator ─────────────────────────────────────────────────────────

    def _build_ev_panel(self) -> QWidget:
        group = QGroupBox("EV Calculator")
        group.setFixedWidth(340)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(12)

        fields = QFormLayout()
        fields.setSpacing(10)
        fields.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._ev_odds = QSpinBox()
        self._ev_odds.setRange(-10000, 10000)
        self._ev_odds.setValue(-110)

        self._ev_prob = QDoubleSpinBox()
        self._ev_prob.setRange(0.0, 100.0)
        self._ev_prob.setDecimals(1)
        self._ev_prob.setSuffix(" %")
        self._ev_prob.setValue(55.0)

        fields.addRow("American Odds",    self._ev_odds)
        fields.addRow("Win Probability",  self._ev_prob)

        layout.addLayout(fields)

        calc_btn = QPushButton("Calculate EV")
        calc_btn.clicked.connect(self._run_ev)
        layout.addWidget(calc_btn)

        # Result area
        self._ev_result_frame = QFrame()
        self._ev_result_frame.setObjectName("card")
        self._ev_result_frame.hide()
        ev_result_layout = QVBoxLayout(self._ev_result_frame)
        ev_result_layout.setSpacing(8)
        ev_result_layout.setContentsMargins(14, 14, 14, 14)

        self._ev_grade_label  = QLabel()
        self._ev_grade_label.setStyleSheet("font-size: 32px; font-weight: 700;")
        self._ev_grade_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._ev_action_label = QLabel()
        self._ev_action_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        self._ev_action_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._ev_rows_layout  = QFormLayout()
        self._ev_rows_layout.setSpacing(6)

        self._ev_sb_label   = QLabel()
        self._ev_edge_label = QLabel()
        self._ev_ev_label   = QLabel()
        self._ev_summ_label = QLabel()
        self._ev_summ_label.setObjectName("muted")
        self._ev_summ_label.setWordWrap(True)

        self._ev_rows_layout.addRow("Sportsbook Prob:",  self._ev_sb_label)
        self._ev_rows_layout.addRow("Edge:",             self._ev_edge_label)
        self._ev_rows_layout.addRow("Expected Value:",   self._ev_ev_label)

        ev_result_layout.addWidget(self._ev_grade_label)
        ev_result_layout.addWidget(self._ev_action_label)
        ev_result_layout.addLayout(self._ev_rows_layout)
        ev_result_layout.addWidget(self._ev_summ_label)

        layout.addWidget(self._ev_result_frame)
        layout.addStretch()

        return group

    def _run_ev(self):
        odds = self._ev_odds.value()
        prob = self._ev_prob.value()

        sb = sportsbook_probability(odds) * 100
        ev = expected_value(odds, prob / 100) * 100
        edge = prob - sb
        result = recommendation(ev)
        grade  = result["grade"]

        color = GREEN if ev >= 5 else (YELLOW if ev >= 0 else RED)

        self._ev_grade_label.setText(grade)
        self._ev_grade_label.setStyleSheet(f"font-size: 32px; font-weight: 700; color: {color};")
        self._ev_action_label.setText(result["action"])
        self._ev_action_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {color};")
        self._ev_sb_label.setText(f"{sb:.1f}%")
        self._ev_edge_label.setText(f"{edge:+.1f}%")
        self._ev_ev_label.setText(f"{ev:+.2f}%")
        self._ev_summ_label.setText(result["summary"])

        self._ev_result_frame.show()

    # ── Prop Analysis ─────────────────────────────────────────────────────────

    def _build_prop_panel(self) -> QWidget:
        group = QGroupBox("Single Prop Analysis")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(12)

        fields = QFormLayout()
        fields.setSpacing(10)
        fields.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._pa_player = QLineEdit()
        self._pa_player.setPlaceholderText("Player name")

        self._pa_team   = QLineEdit()
        self._pa_team.setPlaceholderText("Team abbreviation")

        self._pa_sport  = QComboBox()
        self._pa_sport.addItems(["NBA", "WNBA", "NFL", "MLB"])

        self._pa_stat   = QComboBox()
        for st in StatType:
            self._pa_stat.addItem(st.value, userData=st)

        self._pa_line   = QDoubleSpinBox()
        self._pa_line.setRange(0, 1000)
        self._pa_line.setDecimals(1)
        self._pa_line.setValue(20.5)

        self._pa_proj   = QDoubleSpinBox()
        self._pa_proj.setRange(0, 1000)
        self._pa_proj.setDecimals(1)
        self._pa_proj.setValue(23.0)

        fields.addRow("Player",     self._pa_player)
        fields.addRow("Team",       self._pa_team)
        fields.addRow("Sport",      self._pa_sport)
        fields.addRow("Stat",       self._pa_stat)
        fields.addRow("Line",       self._pa_line)
        fields.addRow("Projection", self._pa_proj)

        layout.addLayout(fields)

        analyze_btn = QPushButton("Analyze Prop")
        analyze_btn.clicked.connect(self._run_prop_analysis)
        layout.addWidget(analyze_btn)

        # Result area
        self._pa_result_frame = QFrame()
        self._pa_result_frame.setObjectName("card")
        self._pa_result_frame.hide()
        pa_result_layout = QVBoxLayout(self._pa_result_frame)
        pa_result_layout.setSpacing(8)
        pa_result_layout.setContentsMargins(14, 14, 14, 14)

        self._pa_grade_label    = QLabel()
        self._pa_grade_label.setStyleSheet("font-size: 32px; font-weight: 700;")
        self._pa_grade_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._pa_action_label   = QLabel()
        self._pa_action_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        self._pa_action_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._pa_rows           = QFormLayout()
        self._pa_rows.setSpacing(6)

        self._pa_edge_label     = QLabel()
        self._pa_conf_label     = QLabel()
        self._pa_direction_label= QLabel()

        self._pa_rows.addRow("Edge:",       self._pa_edge_label)
        self._pa_rows.addRow("Confidence:", self._pa_conf_label)
        self._pa_rows.addRow("Direction:",  self._pa_direction_label)

        pa_result_layout.addWidget(self._pa_grade_label)
        pa_result_layout.addWidget(self._pa_action_label)
        pa_result_layout.addLayout(self._pa_rows)

        layout.addWidget(self._pa_result_frame)
        layout.addStretch()

        return group

    def _run_prop_analysis(self):
        player_name = self._pa_player.text().strip() or "Player"
        team        = self._pa_team.text().strip() or "—"
        sport       = self._pa_sport.currentText()
        stat        = self._pa_stat.currentData()
        line        = self._pa_line.value()
        projection  = self._pa_proj.value()

        player = Player(name=player_name, team=team, sport=sport)
        edge   = calculate_edge(line, projection)
        conf   = calculate_confidence(edge)

        prop = Prop(
            player=player,
            stat=stat,
            line=line,
            projection=projection,
            edge=edge,
            confidence=conf,
        )

        # Derive a simple grade from confidence tiers
        if conf >= 80:
            grade, action, color = "A", "🔥 Strong Consideration", GREEN
        elif conf >= 70:
            grade, action, color = "B", "🟢 Consider", GREEN
        elif conf >= 60:
            grade, action, color = "C", "🟡 Lean", YELLOW
        else:
            grade, action, color = "F", "🔴 Pass", RED

        direction = "OVER" if edge > 0 else ("UNDER" if edge < 0 else "EVEN")

        self._pa_grade_label.setText(grade)
        self._pa_grade_label.setStyleSheet(
            f"font-size: 32px; font-weight: 700; color: {color};"
        )
        self._pa_action_label.setText(action)
        self._pa_action_label.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {color};"
        )
        self._pa_edge_label.setText(f"{edge:+.1f}")
        self._pa_conf_label.setText(f"{conf:.0f}%")
        self._pa_direction_label.setText(direction)
        self._pa_direction_label.setStyleSheet(f"color: {color}; font-weight: 700;")

        self._pa_result_frame.show()
