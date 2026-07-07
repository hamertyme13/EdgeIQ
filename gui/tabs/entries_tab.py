"""
Entries tab — multi-prop entry builder with analysis panel.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
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
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models.player import Player
from models.prop import Prop
from models.entry import Entry
from models.platform import Platform
from models.stat_type import StatType
from analytics.prop_metrics import calculate_edge, calculate_confidence
from analytics.entry_recommendation import recommendation as entry_recommendation
from analytics.risk import calculate_entry_risk
from analytics.correlation import detect_correlations
from repository.repositories.entry_repository import EntryRepository
from gui.styles import ACCENT, GREEN, RED, YELLOW, MUTED, CYAN


class EntriesTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._props: list[Prop] = []
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(20)

        root.addWidget(self._build_builder_panel())
        root.addWidget(self._build_analysis_panel())

    # ── Left: Prop builder ────────────────────────────────────────────────────

    def _build_builder_panel(self) -> QWidget:
        container = QWidget()
        container.setFixedWidth(360)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # Platform selection
        platform_group = QGroupBox("Platform")
        pl_layout = QHBoxLayout(platform_group)
        pl_layout.setContentsMargins(12, 18, 12, 12)
        self._platform_combo = QComboBox()
        for p in Platform:
            self._platform_combo.addItem(p.value, userData=p)
        pl_layout.addWidget(self._platform_combo)
        layout.addWidget(platform_group)

        # Prop input
        prop_group = QGroupBox("Add Prop")
        prop_layout = QVBoxLayout(prop_group)
        prop_layout.setContentsMargins(12, 18, 12, 12)
        prop_layout.setSpacing(10)

        fields = QFormLayout()
        fields.setSpacing(8)
        fields.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._player_input = QLineEdit()
        self._player_input.setPlaceholderText("Player name")

        self._team_input   = QLineEdit()
        self._team_input.setPlaceholderText("Team abbrev.")

        self._sport_combo  = QComboBox()
        self._sport_combo.addItems(["NBA", "WNBA", "NFL", "MLB"])

        self._stat_combo   = QComboBox()
        for st in StatType:
            self._stat_combo.addItem(st.value, userData=st)

        self._line_spin    = QDoubleSpinBox()
        self._line_spin.setRange(0, 1000)
        self._line_spin.setDecimals(1)
        self._line_spin.setValue(20.5)

        self._proj_spin    = QDoubleSpinBox()
        self._proj_spin.setRange(0, 1000)
        self._proj_spin.setDecimals(1)
        self._proj_spin.setValue(23.0)

        fields.addRow("Player",     self._player_input)
        fields.addRow("Team",       self._team_input)
        fields.addRow("Sport",      self._sport_combo)
        fields.addRow("Stat",       self._stat_combo)
        fields.addRow("Line",       self._line_spin)
        fields.addRow("Projection", self._proj_spin)

        prop_layout.addLayout(fields)

        self._prop_feedback = QLabel("")
        self._prop_feedback.setObjectName("muted")
        self._prop_feedback.setWordWrap(True)
        prop_layout.addWidget(self._prop_feedback)

        add_btn = QPushButton("+ Add Prop to Entry")
        add_btn.clicked.connect(self._add_prop)
        prop_layout.addWidget(add_btn)

        layout.addWidget(prop_group)

        # Props in entry list
        entry_group = QGroupBox("Current Entry (0 props)")
        self._entry_group = entry_group
        entry_layout = QVBoxLayout(entry_group)
        entry_layout.setContentsMargins(12, 18, 12, 12)
        entry_layout.setSpacing(8)

        self._props_table = QTableWidget()
        self._props_table.setColumnCount(4)
        self._props_table.setHorizontalHeaderLabels(["Player", "Stat", "Line", "Edge"])
        self._props_table.setAlternatingRowColors(True)
        self._props_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._props_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._props_table.verticalHeader().setVisible(False)
        self._props_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._props_table.setFixedHeight(160)
        entry_layout.addWidget(self._props_table)

        btns = QHBoxLayout()
        self._remove_btn = QPushButton("Remove Selected")
        self._remove_btn.setObjectName("secondary")
        self._remove_btn.clicked.connect(self._remove_prop)

        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.setObjectName("danger")
        self._clear_btn.clicked.connect(self._clear_entry)

        btns.addWidget(self._remove_btn)
        btns.addWidget(self._clear_btn)
        entry_layout.addLayout(btns)

        layout.addWidget(entry_group)

        # Analyze + Save buttons
        actions = QHBoxLayout()
        self._analyze_btn = QPushButton("Analyze Entry")
        self._analyze_btn.clicked.connect(self._analyze_entry)
        self._save_entry_btn = QPushButton("Save Entry")
        self._save_entry_btn.setObjectName("secondary")
        self._save_entry_btn.clicked.connect(self._save_entry)
        self._save_entry_btn.setEnabled(False)

        actions.addWidget(self._analyze_btn)
        actions.addWidget(self._save_entry_btn)
        layout.addLayout(actions)

        layout.addStretch()
        return container

    # ── Right: Analysis panel ─────────────────────────────────────────────────

    def _build_analysis_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Entry Intelligence")
        title.setObjectName("section-title")
        layout.addWidget(title)

        self._analysis_placeholder = QLabel(
            "Build an entry of 2 or more props,\nthen click Analyze Entry."
        )
        self._analysis_placeholder.setObjectName("muted")
        self._analysis_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._analysis_placeholder)

        # Result widgets (hidden until analyzed)
        self._analysis_result = QWidget()
        self._analysis_result.hide()
        result_layout = QVBoxLayout(self._analysis_result)
        result_layout.setSpacing(12)

        self._grade_label  = QLabel()
        self._grade_label.setStyleSheet("font-size: 36px; font-weight: 700;")
        self._grade_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._action_label = QLabel()
        self._action_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        self._action_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        stats_row = QHBoxLayout()
        self._avg_conf_card = _MiniCard("Avg Confidence", "—")
        self._avg_edge_card = _MiniCard("Avg Edge", "—")
        self._risk_card     = _MiniCard("Risk Level", "—")
        stats_row.addWidget(self._avg_conf_card)
        stats_row.addWidget(self._avg_edge_card)
        stats_row.addWidget(self._risk_card)

        self._reason_label = QLabel()
        self._reason_label.setObjectName("muted")
        self._reason_label.setWordWrap(True)
        self._reason_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._warnings_label = QLabel()
        self._warnings_label.setStyleSheet(f"color: {YELLOW}; font-size: 12px;")
        self._warnings_label.setWordWrap(True)

        result_layout.addWidget(self._grade_label)
        result_layout.addWidget(self._action_label)
        result_layout.addLayout(stats_row)
        result_layout.addWidget(self._reason_label)
        result_layout.addWidget(self._warnings_label)

        layout.addWidget(self._analysis_result)
        layout.addStretch()
        return frame

    # ── Logic ─────────────────────────────────────────────────────────────────

    def _add_prop(self):
        player_name = self._player_input.text().strip()
        team        = self._team_input.text().strip()

        if not player_name or not team:
            self._prop_feedback.setText("Player and Team are required.")
            self._prop_feedback.setStyleSheet(f"color: {RED}; font-size: 12px;")
            return

        sport = self._sport_combo.currentText()
        stat  = self._stat_combo.currentData()
        line  = self._line_spin.value()
        proj  = self._proj_spin.value()

        edge  = calculate_edge(line, proj)
        conf  = calculate_confidence(edge)

        prop  = Prop(
            player=Player(name=player_name, team=team, sport=sport),
            stat=stat,
            line=line,
            projection=proj,
            edge=edge,
            confidence=conf,
        )

        self._props.append(prop)
        self._prop_feedback.setText(f"✓ {player_name} added.")
        self._prop_feedback.setStyleSheet(f"color: {GREEN}; font-size: 12px;")
        self._player_input.clear()
        self._team_input.clear()
        self._refresh_props_table()

    def _remove_prop(self):
        row = self._props_table.currentRow()
        if 0 <= row < len(self._props):
            self._props.pop(row)
            self._refresh_props_table()

    def _clear_entry(self):
        self._props.clear()
        self._refresh_props_table()
        self._analysis_result.hide()
        self._analysis_placeholder.show()
        self._save_entry_btn.setEnabled(False)

    def _refresh_props_table(self):
        n = len(self._props)
        self._entry_group.setTitle(f"Current Entry ({n} prop{'s' if n != 1 else ''})")
        self._props_table.setRowCount(n)

        for row, prop in enumerate(self._props):
            center = Qt.AlignmentFlag.AlignCenter

            def _item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                return item

            self._props_table.setItem(row, 0, _item(prop.player.name))
            self._props_table.setItem(row, 1, _item(prop.stat.value))
            self._props_table.setItem(row, 2, _item(f"{prop.line:.1f}", center))

            edge_item = _item(f"{prop.edge:+.1f}", center)
            edge_item.setForeground(QColor(GREEN if prop.edge >= 0 else RED))
            self._props_table.setItem(row, 3, edge_item)

    def _analyze_entry(self):
        if len(self._props) < 2:
            self._prop_feedback.setText("Add at least 2 props to analyze.")
            self._prop_feedback.setStyleSheet(f"color: {YELLOW}; font-size: 12px;")
            return

        platform = self._platform_combo.currentData()
        entry = Entry(platform=platform, props=list(self._props))

        result      = entry_recommendation(entry)
        risk_result = calculate_entry_risk(entry.props)
        warnings    = detect_correlations(entry)

        grade  = result["grade"]
        action = result["action"]
        reason = result["reason"]
        color  = {"green": GREEN, "yellow": YELLOW, "cyan": CYAN, "red": RED}.get(
            result["color"], ACCENT
        )

        self._grade_label.setText(grade)
        self._grade_label.setStyleSheet(f"font-size: 36px; font-weight: 700; color: {color};")
        self._action_label.setText(action)
        self._action_label.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {color};")
        self._reason_label.setText(reason)

        self._avg_conf_card.set_value(f"{risk_result.average_confidence:.1f}%")
        self._avg_edge_card.set_value(f"{risk_result.average_edge:+.2f}")
        risk_color = {
            "Low": GREEN, "Medium": YELLOW, "High": RED
        }.get(risk_result.risk.value, MUTED)
        self._risk_card.set_value(risk_result.risk.value, color=risk_color)

        if warnings:
            self._warnings_label.setText("⚠ " + "  ·  ".join(warnings))
        else:
            self._warnings_label.setText("")

        self._analysis_placeholder.hide()
        self._analysis_result.show()
        self._save_entry_btn.setEnabled(True)

    def _save_entry(self):
        if not self._props:
            return

        platform = self._platform_combo.currentData()
        entry = Entry(platform=platform, props=list(self._props))

        try:
            EntryRepository.save(entry)
            self._prop_feedback.setText("✓ Entry saved.")
            self._prop_feedback.setStyleSheet(f"color: {GREEN}; font-size: 12px;")
            self._save_entry_btn.setEnabled(False)
        except Exception as e:
            self._prop_feedback.setText(f"Save failed: {e}")
            self._prop_feedback.setStyleSheet(f"color: {RED}; font-size: 12px;")


# ── Helper widget ─────────────────────────────────────────────────────────────

class _MiniCard(QFrame):
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(2)

        self._value = QLabel(value)
        self._value.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {ACCENT};")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = QLabel(label)
        lbl.setObjectName("stat-label")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._value)
        layout.addWidget(lbl)

    def set_value(self, value: str, color: str = ACCENT):
        self._value.setText(value)
        self._value.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {color};")
