"""
Entries tab — multi-prop entry builder with analysis panel.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
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
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from models.player import Player
from models.prop import Prop
from models.entry import Entry
from models.platform import Platform
from models.stat_type import StatType
from analytics.entry_suggestions import SuggestedEntry, suggest_entries
from analytics.prop_metrics import calculate_edge, calculate_confidence
from analytics.projection import auto_projection
from analytics.entry_recommendation import recommendation as entry_recommendation
from analytics.risk import calculate_entry_risk
from analytics.correlation import detect_correlations
from repository.repositories.entry_repository import EntryRepository
from utils.stat_normalization import stat_type_from_text
from utils.logging import get_logger
import data.providers.prizepicks as _pp
import data.providers.underdog as _ud

logger = get_logger(__name__)
from gui.styles import ACCENT, GREEN, RED, YELLOW, MUTED, CYAN


def _platform_from_text(value: str) -> Platform:
    for platform in Platform:
        if platform.value.lower() == (value or "").lower():
            return platform
    return Platform.PRIZEPICKS


def _stat_from_text(value: str) -> StatType:
    return stat_type_from_text(value)


class _SuggestionFetcher(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, sport: str, platform: Platform, parent=None):
        super().__init__(parent)
        self.sport = sport
        self.platform = platform

    def run(self):
        try:
            if self.platform == Platform.PRIZEPICKS:
                props = _pp.fetch_projections(limit=1000)
            else:
                props = _ud.fetch_projections()
            self.finished.emit(suggest_entries(props, self.sport, self.platform))
        except Exception as e:
            logger.exception("Failed to generate suggested entries")
            self.error.emit(str(e))


class EntriesTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._props: list[Prop] = []
        self._last_analysis_entry: Entry | None = None
        self._editing_row: int | None = None
        self._suggestion_fetcher: _SuggestionFetcher | None = None
        self._suggestions: list[SuggestedEntry] = []
        self._build_ui()
        self.refresh_pending_entries()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        root.addWidget(self._build_builder_panel())
        root.addWidget(self._build_analysis_panel())

    # ── Left: Prop builder ────────────────────────────────────────────────────

    def _build_builder_panel(self) -> QWidget:
        container = QWidget()
        container.setFixedWidth(340)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Platform selection
        platform_group = QGroupBox("Platform")
        pl_layout = QHBoxLayout(platform_group)
        pl_layout.setContentsMargins(12, 14, 12, 10)
        self._platform_combo = QComboBox()
        for p in Platform:
            self._platform_combo.addItem(p.value, userData=p)
        pl_layout.addWidget(self._platform_combo)
        layout.addWidget(platform_group)

        # Prop input
        prop_group = QGroupBox("Add Prop")
        prop_layout = QVBoxLayout(prop_group)
        prop_layout.setContentsMargins(12, 14, 12, 10)
        prop_layout.setSpacing(8)

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

        self._add_btn = QPushButton("+ Add Prop to Entry")
        self._add_btn.clicked.connect(self._add_or_update_prop)
        prop_layout.addWidget(self._add_btn)

        layout.addWidget(prop_group)

        # Props in entry list
        entry_group = QGroupBox("Current Entry (0 props)")
        self._entry_group = entry_group
        entry_layout = QVBoxLayout(entry_group)
        entry_layout.setContentsMargins(12, 14, 12, 10)
        entry_layout.setSpacing(8)

        self._props_table = QTableWidget()
        self._props_table.setColumnCount(4)
        self._props_table.setHorizontalHeaderLabels(["Player", "Stat", "Line", "Edge"])
        self._props_table.setAlternatingRowColors(True)
        self._props_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._props_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._props_table.verticalHeader().setVisible(False)
        self._props_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._props_table.cellClicked.connect(self._load_prop_for_editing)
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
        self._save_entry_btn = QPushButton("Place Entry")
        self._save_entry_btn.setObjectName("secondary")
        self._save_entry_btn.clicked.connect(self._ask_to_place_entry)
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
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Entry Intelligence")
        title.setObjectName("section-title")
        layout.addWidget(title)

        work_tabs = QTabWidget()
        work_tabs.setDocumentMode(True)
        layout.addWidget(work_tabs)

        analysis_tab = QWidget()
        analysis_layout = QVBoxLayout(analysis_tab)
        analysis_layout.setContentsMargins(0, 12, 0, 0)
        analysis_layout.setSpacing(12)

        self._analysis_placeholder = QLabel(
            "Build an entry of 2 or more props,\nthen click Analyze Entry."
        )
        self._analysis_placeholder.setObjectName("muted")
        self._analysis_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        analysis_layout.addWidget(self._analysis_placeholder)

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

        analysis_layout.addWidget(self._analysis_result)
        analysis_layout.addStretch()
        work_tabs.addTab(analysis_tab, "Analysis")

        suggestions_tab = QWidget()
        suggestions_tab_layout = QVBoxLayout(suggestions_tab)
        suggestions_tab_layout.setContentsMargins(0, 12, 0, 0)
        suggestions_tab_layout.setSpacing(10)
        suggestions_group = QGroupBox("Suggested Entries")
        suggestions_layout = QVBoxLayout(suggestions_group)
        suggestions_layout.setContentsMargins(12, 16, 12, 12)
        suggestions_layout.setSpacing(8)

        suggestion_controls = QHBoxLayout()
        self._suggest_sport_combo = QComboBox()
        self._suggest_sport_combo.addItems(["WNBA", "NBA", "NFL", "MLB"])
        suggestion_controls.addWidget(self._suggest_sport_combo)

        self._suggest_platform_combo = QComboBox()
        for platform in Platform:
            self._suggest_platform_combo.addItem(platform.value, userData=platform)
        suggestion_controls.addWidget(self._suggest_platform_combo)

        self._suggest_btn = QPushButton("Generate Top 5")
        self._suggest_btn.clicked.connect(self._generate_suggestions)
        suggestion_controls.addWidget(self._suggest_btn)
        suggestions_layout.addLayout(suggestion_controls)

        self._suggestions_table = QTableWidget()
        self._suggestions_table.setColumnCount(5)
        self._suggestions_table.setHorizontalHeaderLabels(
            ["Rank", "Props", "Score", "Grade", "Action"]
        )
        self._suggestions_table.setAlternatingRowColors(True)
        self._suggestions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._suggestions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._suggestions_table.verticalHeader().setVisible(False)
        self._suggestions_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._suggestions_table.setFixedHeight(150)
        suggestions_layout.addWidget(self._suggestions_table)

        self._load_suggestion_btn = QPushButton("Load Selected Suggestion")
        self._load_suggestion_btn.setObjectName("secondary")
        self._load_suggestion_btn.clicked.connect(self._load_selected_suggestion)
        suggestions_layout.addWidget(self._load_suggestion_btn)

        self._suggestions_feedback = QLabel("")
        self._suggestions_feedback.setObjectName("muted")
        self._suggestions_feedback.setWordWrap(True)
        suggestions_layout.addWidget(self._suggestions_feedback)

        suggestions_tab_layout.addWidget(suggestions_group)
        suggestions_tab_layout.addStretch()
        work_tabs.addTab(suggestions_tab, "Suggestions")

        pending_tab = QWidget()
        pending_tab_layout = QVBoxLayout(pending_tab)
        pending_tab_layout.setContentsMargins(0, 12, 0, 0)
        pending_tab_layout.setSpacing(10)
        pending_group = QGroupBox("Pending Entries")
        pending_layout = QVBoxLayout(pending_group)
        pending_layout.setContentsMargins(12, 16, 12, 12)
        pending_layout.setSpacing(8)

        self._pending_table = QTableWidget()
        self._pending_table.setColumnCount(5)
        self._pending_table.setHorizontalHeaderLabels(
            ["ID", "Props", "Avg Conf", "Avg Edge", "Placed"]
        )
        self._pending_table.setAlternatingRowColors(True)
        self._pending_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pending_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pending_table.verticalHeader().setVisible(False)
        self._pending_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._pending_table.setFixedHeight(190)
        pending_layout.addWidget(self._pending_table)

        settle_actions = QHBoxLayout()
        self._win_btn = QPushButton("Win")
        self._win_btn.clicked.connect(lambda: self._settle_selected_entry("Win"))
        self._loss_btn = QPushButton("Loss")
        self._loss_btn.setObjectName("danger")
        self._loss_btn.clicked.connect(lambda: self._settle_selected_entry("Loss"))
        self._push_btn = QPushButton("Push")
        self._push_btn.setObjectName("secondary")
        self._push_btn.clicked.connect(lambda: self._settle_selected_entry("Push"))

        settle_actions.addWidget(self._win_btn)
        settle_actions.addWidget(self._loss_btn)
        settle_actions.addWidget(self._push_btn)
        pending_layout.addLayout(settle_actions)

        self._pending_feedback = QLabel("")
        self._pending_feedback.setObjectName("muted")
        self._pending_feedback.setWordWrap(True)
        pending_layout.addWidget(self._pending_feedback)

        pending_tab_layout.addWidget(pending_group)
        pending_tab_layout.addStretch()
        work_tabs.addTab(pending_tab, "Pending")

        return frame

    # ── Logic ─────────────────────────────────────────────────────────────────

    def add_dashboard_prop(self, prop_data: dict):
        platform = _platform_from_text(prop_data.get("platform", "PrizePicks"))
        stat = _stat_from_text(prop_data.get("stat", ""))
        line = prop_data.get("line")
        line = float(line) if line is not None else 0.0

        self._platform_combo.setCurrentIndex(max(0, self._platform_combo.findData(platform)))

        prop = Prop(
            player=Player(
                name=prop_data.get("player", "Player"),
                team=prop_data.get("team", ""),
                sport=prop_data.get("league", "WNBA"),
            ),
            stat=stat,
            line=line,
            projection=line,
            edge=0.0,
            confidence=0.0,
            platform=platform,
            game=prop_data.get("game", ""),
            needs_projection=True,
            trending_count=int(prop_data.get("trending_count", 0) or 0),
        )

        self._props.append(prop)
        self._refresh_props_table()
        self._prop_feedback.setText(
            f"{prop.player.name} added from Dashboard. Projection will be estimated before analysis."
        )
        self._prop_feedback.setStyleSheet(f"color: {CYAN}; font-size: 12px;")
        self._analysis_result.hide()
        self._analysis_placeholder.show()
        self._save_entry_btn.setEnabled(False)

    def _add_or_update_prop(self):
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
        existing_game = ""
        if self._editing_row is not None and 0 <= self._editing_row < len(self._props):
            existing_game = self._props[self._editing_row].game

        prop  = Prop(
            player=Player(name=player_name, team=team, sport=sport),
            stat=stat,
            line=line,
            projection=proj,
            edge=edge,
            confidence=conf,
            platform=self._platform_combo.currentData(),
            game=existing_game,
            needs_projection=False,
            auto_projected=False,
        )

        if self._editing_row is not None and 0 <= self._editing_row < len(self._props):
            self._props[self._editing_row] = prop
            self._prop_feedback.setText(f"✓ {player_name} updated.")
        else:
            self._props.append(prop)
            self._prop_feedback.setText(f"✓ {player_name} added.")

        self._prop_feedback.setStyleSheet(f"color: {GREEN}; font-size: 12px;")
        self._reset_prop_form()
        self._refresh_props_table()

    def _remove_prop(self):
        row = self._props_table.currentRow()
        if 0 <= row < len(self._props):
            self._props.pop(row)
            self._reset_prop_form()
            self._refresh_props_table()

    def _clear_entry(self):
        self._props.clear()
        self._last_analysis_entry = None
        self._reset_prop_form()
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

            if prop.needs_projection:
                edge_text = "Auto"
            else:
                edge_text = f"{prop.edge:+.1f}{'*' if prop.auto_projected else ''}"
            edge_item = _item(edge_text, center)
            edge_item.setForeground(QColor(YELLOW if prop.needs_projection else (GREEN if prop.edge >= 0 else RED)))
            self._props_table.setItem(row, 3, edge_item)

    def _load_prop_for_editing(self, row: int, column: int):
        if not (0 <= row < len(self._props)):
            return

        prop = self._props[row]
        self._editing_row = row

        self._player_input.setText(prop.player.name)
        self._team_input.setText(prop.player.team)
        self._sport_combo.setCurrentText(prop.player.sport)
        self._stat_combo.setCurrentIndex(max(0, self._stat_combo.findData(prop.stat)))
        self._line_spin.setValue(prop.line)
        self._proj_spin.setValue(prop.projection)
        self._platform_combo.setCurrentIndex(max(0, self._platform_combo.findData(prop.platform)))
        self._add_btn.setText("Update Selected Prop")

    def _reset_prop_form(self):
        self._editing_row = None
        self._player_input.clear()
        self._team_input.clear()
        self._add_btn.setText("+ Add Prop to Entry")

    def _analyze_entry(self):
        if len(self._props) < 2:
            self._prop_feedback.setText("Add at least 2 props to analyze.")
            self._prop_feedback.setStyleSheet(f"color: {YELLOW}; font-size: 12px;")
            return

        auto_count = self._auto_project_missing_props()
        if auto_count:
            self._prop_feedback.setText(
                f"Auto-projected {auto_count} prop{'s' if auto_count != 1 else ''}. Review before placing."
            )
            self._prop_feedback.setStyleSheet(f"color: {CYAN}; font-size: 12px;")

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
        self._last_analysis_entry = entry
        self._ask_to_place_entry()

    def _auto_project_missing_props(self) -> int:
        count = 0
        for prop in self._props:
            if not prop.needs_projection:
                continue

            prop.projection = auto_projection(prop.line, prop.trending_count)
            prop.edge = calculate_edge(prop.line, prop.projection)
            prop.confidence = calculate_confidence(prop.edge)
            prop.needs_projection = False
            prop.auto_projected = True
            count += 1

        if count:
            self._refresh_props_table()

        return count

    def _generate_suggestions(self):
        if self._suggestion_fetcher and self._suggestion_fetcher.isRunning():
            return

        sport = self._suggest_sport_combo.currentText()
        platform = self._suggest_platform_combo.currentData()
        self._suggestions_feedback.setText(f"Generating {sport} suggestions...")
        self._suggestions_table.setRowCount(0)
        self._suggest_btn.setEnabled(False)

        self._suggestion_fetcher = _SuggestionFetcher(sport, platform, parent=self)
        self._suggestion_fetcher.finished.connect(self._on_suggestions_ready)
        self._suggestion_fetcher.error.connect(self._on_suggestions_error)
        self._suggestion_fetcher.start()

    def _on_suggestions_ready(self, suggestions: list[SuggestedEntry]):
        self._suggest_btn.setEnabled(True)
        self._suggestions = suggestions
        self._suggestions_table.setRowCount(len(suggestions))

        if not suggestions:
            self._suggestions_feedback.setText("No suggested entries available for that sport.")
            return

        for row, suggestion in enumerate(suggestions):
            center = Qt.AlignmentFlag.AlignCenter

            def _item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                return item

            props = " + ".join(
                f"{prop.player.name} {prop.stat.value} {prop.line:g}"
                for prop in suggestion.entry.props
            )

            rank_item = _item(str(suggestion.rank), center)
            rank_item.setData(Qt.ItemDataRole.UserRole, row)
            self._suggestions_table.setItem(row, 0, rank_item)
            self._suggestions_table.setItem(row, 1, _item(props))
            self._suggestions_table.setItem(row, 2, _item(f"{suggestion.score:.1f}", center))
            self._suggestions_table.setItem(row, 3, _item(suggestion.grade, center))
            self._suggestions_table.setItem(row, 4, _item(suggestion.action, center))

        self._suggestions_feedback.setText("Top 5 generated. Load one to review and place.")
        self._suggestions_table.resizeColumnToContents(0)
        self._suggestions_table.resizeColumnToContents(2)
        self._suggestions_table.resizeColumnToContents(3)
        self._suggestions_table.resizeColumnToContents(4)

    def _on_suggestions_error(self, message: str):
        self._suggest_btn.setEnabled(True)
        self._suggestions_feedback.setText(f"Suggestion generation failed: {message}")

    def _load_selected_suggestion(self):
        row = self._suggestions_table.currentRow()
        if row < 0 or row >= len(self._suggestions):
            self._suggestions_feedback.setText("Select a suggested entry first.")
            return

        suggestion = self._suggestions[row]
        self._props = list(suggestion.entry.props)
        self._last_analysis_entry = None
        self._reset_prop_form()
        self._refresh_props_table()
        self._suggestions_feedback.setText(
            f"Loaded suggestion #{suggestion.rank}. Review it, then analyze/place."
        )
        self._suggestions_feedback.setStyleSheet(f"color: {GREEN}; font-size: 12px;")

    def _ask_to_place_entry(self):
        if not self._last_analysis_entry:
            self._analyze_entry()
            return

        answer = QMessageBox.question(
            self,
            "Place Entry",
            "Will you place this entry?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if answer == QMessageBox.StandardButton.Yes:
            self._place_entry(self._last_analysis_entry)
        else:
            self._prop_feedback.setText("Entry not saved. You can adjust it or clear it.")
            self._prop_feedback.setStyleSheet(f"color: {MUTED}; font-size: 12px;")

    def _place_entry(self, entry: Entry):
        if not entry.props:
            return

        try:
            entry_id = EntryRepository.save(entry, status="Pending")
            self._prop_feedback.setText(
                f"Entry #{entry_id} saved as pending. Return here after the games to mark the result."
            )
            self._prop_feedback.setStyleSheet(f"color: {GREEN}; font-size: 12px;")
            self._props.clear()
            self._last_analysis_entry = None
            self._reset_prop_form()
            self._refresh_props_table()
            self._analysis_result.hide()
            self._analysis_placeholder.show()
            self._save_entry_btn.setEnabled(False)
            self.refresh_pending_entries()
        except Exception as e:
            logger.exception("Failed to save entry")
            self._prop_feedback.setText(f"Save failed: {e}")
            self._prop_feedback.setStyleSheet(f"color: {RED}; font-size: 12px;")

    def refresh_pending_entries(self):
        try:
            entries = EntryRepository.pending()
        except Exception as e:
            logger.exception("Failed to load pending entries")
            self._pending_feedback.setText(f"Pending entries unavailable: {e}")
            return

        self._pending_table.setRowCount(len(entries))
        self._pending_feedback.setText(
            "No pending entries." if not entries else "Select a pending entry to record its result."
        )

        for row, entry in enumerate(entries):
            center = Qt.AlignmentFlag.AlignCenter

            def _item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                return item

            prop_names = ", ".join(prop["player"] for prop in entry["props"])
            placed = entry["placed_at"].strftime("%b %-d, %I:%M %p") if entry["placed_at"] else ""

            id_item = _item(str(entry["id"]), center)
            id_item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self._pending_table.setItem(row, 0, id_item)
            self._pending_table.setItem(row, 1, _item(prop_names))
            self._pending_table.setItem(row, 2, _item(f"{entry['average_confidence']:.1f}%", center))
            self._pending_table.setItem(row, 3, _item(f"{entry['average_edge']:+.2f}", center))
            self._pending_table.setItem(row, 4, _item(placed, center))

        self._pending_table.resizeColumnToContents(0)
        self._pending_table.resizeColumnToContents(2)
        self._pending_table.resizeColumnToContents(3)
        self._pending_table.resizeColumnToContents(4)

    def _settle_selected_entry(self, result: str):
        row = self._pending_table.currentRow()
        if row < 0:
            self._pending_feedback.setText("Select a pending entry first.")
            self._pending_feedback.setStyleSheet(f"color: {YELLOW}; font-size: 12px;")
            return

        entry_id = self._pending_table.item(row, 0).data(Qt.ItemDataRole.UserRole)

        try:
            EntryRepository.settle(int(entry_id), result)
            self._pending_feedback.setText(f"Entry #{entry_id} marked {result}.")
            self._pending_feedback.setStyleSheet(f"color: {GREEN}; font-size: 12px;")
            self.refresh_pending_entries()
        except Exception as e:
            logger.exception("Failed to settle entry")
            self._pending_feedback.setText(f"Could not update entry: {e}")
            self._pending_feedback.setStyleSheet(f"color: {RED}; font-size: 12px;")


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
