"""
Analysis tab — EV Calculator (with Kelly + break-even), single-prop analysis
(with form weighting), and Line Shopping (PrizePicks vs Underdog side-by-side).
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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analytics.ev import expected_value, sportsbook_probability
from analytics.recommendation import recommendation
from analytics.prop_recommendation import recommendation as prop_recommendation
from analytics.prop_metrics import calculate_edge, calculate_confidence
from analytics.kelly import kelly_fraction, half_kelly, suggested_wager, breakeven_probability
from analytics.form import weighted_projection, form_signal
from models.player import Player
from models.prop import Prop
from models.stat_type import StatType
from services.dashboard import get_starting_bankroll
import data.providers.prizepicks as _pp
import data.providers.underdog as _ud
from gui.styles import ACCENT, ACCENT2, GREEN, RED, YELLOW, SURFACE, BORDER, TEXT, MUTED, CYAN
from utils.logging import get_logger

logger = get_logger(__name__)


# ── Line shopping background fetcher ─────────────────────────────────────────

class _ShopFetcher(QThread):
    finished = pyqtSignal(list, list)   # pp_props, ud_props
    error    = pyqtSignal(str)

    def __init__(self, player: str, stat: str, sport: str, parent=None):
        super().__init__(parent)
        self.player = player
        self.stat   = stat
        self.sport  = sport

    def run(self):
        try:
            pp = _pp.fetch_projections()
            ud = _ud.fetch_projections()

            name_lower = self.player.lower()
            stat_lower = self.stat.lower()
            sport_upper = self.sport.upper()

            def match(props):
                return [
                    p for p in props
                    if name_lower in p["player"].lower()
                    and stat_lower in p["stat"].lower()
                    and (not sport_upper or p["league"] == sport_upper)
                ]

            self.finished.emit(match(pp), match(ud))
        except Exception as e:
            logger.exception("Line shopping fetch failed")
            self.error.emit(str(e))


# ── Main tab ──────────────────────────────────────────────────────────────────

class AnalysisTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shop_fetcher: _ShopFetcher | None = None
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        # Left column: EV Calc + Line Shopping stacked
        left = QVBoxLayout()
        left.setSpacing(16)
        left.addWidget(self._build_ev_panel())
        left.addWidget(self._build_line_shop_panel())
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(360)

        root.addWidget(left_widget)
        root.addWidget(self._build_prop_panel())

    # ── EV Calculator ─────────────────────────────────────────────────────────

    def _build_ev_panel(self) -> QWidget:
        group = QGroupBox("EV Calculator")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(10)

        fields = QFormLayout()
        fields.setSpacing(8)
        fields.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._ev_odds = QSpinBox()
        self._ev_odds.setRange(-10000, 10000)
        self._ev_odds.setValue(-110)

        self._ev_prob = QDoubleSpinBox()
        self._ev_prob.setRange(0.0, 100.0)
        self._ev_prob.setDecimals(1)
        self._ev_prob.setSuffix(" %")
        self._ev_prob.setValue(55.0)

        fields.addRow("American Odds",   self._ev_odds)
        fields.addRow("Win Probability", self._ev_prob)
        layout.addLayout(fields)

        QPushButton("Calculate EV").clicked  # placeholder — wired below
        calc_btn = QPushButton("Calculate EV")
        calc_btn.clicked.connect(self._run_ev)
        layout.addWidget(calc_btn)

        # Result card
        self._ev_result = QFrame()
        self._ev_result.setObjectName("card")
        self._ev_result.hide()
        rl = QVBoxLayout(self._ev_result)
        rl.setContentsMargins(12, 12, 12, 12)
        rl.setSpacing(6)

        self._ev_grade  = QLabel()
        self._ev_grade.setStyleSheet("font-size: 28px; font-weight: 700;")
        self._ev_grade.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._ev_action = QLabel()
        self._ev_action.setStyleSheet("font-size: 13px; font-weight: 600;")
        self._ev_action.setAlignment(Qt.AlignmentFlag.AlignCenter)

        rows = QFormLayout()
        rows.setSpacing(5)
        self._ev_sb     = QLabel()
        self._ev_edge   = QLabel()
        self._ev_ev     = QLabel()
        self._ev_beven  = QLabel()
        self._ev_kelly  = QLabel()
        self._ev_hkelly = QLabel()
        self._ev_wager  = QLabel()
        self._ev_summ   = QLabel()
        self._ev_summ.setObjectName("muted")
        self._ev_summ.setWordWrap(True)

        rows.addRow("Sportsbook Prob:",  self._ev_sb)
        rows.addRow("Edge:",             self._ev_edge)
        rows.addRow("Expected Value:",   self._ev_ev)
        rows.addRow("Break-Even %:",     self._ev_beven)
        rows.addRow("Full Kelly:",       self._ev_kelly)
        rows.addRow("Half Kelly:",       self._ev_hkelly)
        rows.addRow("Suggested Wager:",  self._ev_wager)

        rl.addWidget(self._ev_grade)
        rl.addWidget(self._ev_action)
        rl.addLayout(rows)
        rl.addWidget(self._ev_summ)
        layout.addWidget(self._ev_result)
        layout.addStretch()
        return group

    def _run_ev(self):
        odds    = self._ev_odds.value()
        prob    = self._ev_prob.value()
        bankroll = get_starting_bankroll()

        sb      = sportsbook_probability(odds) * 100
        ev      = expected_value(odds, prob / 100) * 100
        edge    = prob - sb
        be      = breakeven_probability(odds) * 100
        fk      = kelly_fraction(odds, prob / 100) * 100
        hk      = half_kelly(odds, prob / 100) * 100
        wager   = suggested_wager(odds, prob / 100, bankroll)
        result  = recommendation(ev)
        color   = GREEN if ev >= 5 else (YELLOW if ev >= 0 else RED)

        self._ev_grade.setText(result["grade"])
        self._ev_grade.setStyleSheet(f"font-size: 28px; font-weight: 700; color: {color};")
        self._ev_action.setText(result["action"])
        self._ev_action.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {color};")
        self._ev_sb.setText(f"{sb:.1f}%")
        self._ev_edge.setText(f"{edge:+.1f}%")
        self._ev_ev.setText(f"{ev:+.2f}%")
        self._ev_beven.setText(f"{be:.1f}%")
        self._ev_kelly.setText(f"{fk:.1f}%  of bankroll")
        self._ev_hkelly.setText(f"{hk:.1f}%  of bankroll")

        wager_color = GREEN if ev >= 0 else RED
        self._ev_wager.setText(f"${wager:.2f}")
        self._ev_wager.setStyleSheet(f"color: {wager_color}; font-weight: 700;")
        self._ev_summ.setText(result["summary"])
        self._ev_result.show()

    # ── Line Shopping panel ───────────────────────────────────────────────────

    def _build_line_shop_panel(self) -> QWidget:
        group = QGroupBox("Line Shopping")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(10)

        fields = QFormLayout()
        fields.setSpacing(8)
        fields.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._shop_player = QLineEdit()
        self._shop_player.setPlaceholderText("e.g. Paige Bueckers")

        self._shop_stat   = QLineEdit()
        self._shop_stat.setPlaceholderText("e.g. Points")

        self._shop_sport  = QComboBox()
        self._shop_sport.addItems(["NBA", "WNBA", "NFL", "MLB"])

        fields.addRow("Player", self._shop_player)
        fields.addRow("Stat",   self._shop_stat)
        fields.addRow("Sport",  self._shop_sport)
        layout.addLayout(fields)

        shop_btn = QPushButton("Compare Lines")
        shop_btn.clicked.connect(self._run_line_shop)
        layout.addWidget(shop_btn)

        self._shop_status = QLabel("")
        self._shop_status.setObjectName("muted")
        layout.addWidget(self._shop_status)

        self._shop_table = QTableWidget()
        self._shop_table.setColumnCount(4)
        self._shop_table.setHorizontalHeaderLabels(["Platform", "Stat", "Line", "🔥 Trending"])
        self._shop_table.setAlternatingRowColors(True)
        self._shop_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._shop_table.verticalHeader().setVisible(False)
        self._shop_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._shop_table.setFixedHeight(140)
        layout.addWidget(self._shop_table)

        return group

    def _run_line_shop(self):
        player = self._shop_player.text().strip()
        stat   = self._shop_stat.text().strip()
        sport  = self._shop_sport.currentText()

        if not player or not stat:
            self._shop_status.setText("Enter a player name and stat.")
            return

        if self._shop_fetcher and self._shop_fetcher.isRunning():
            return

        self._shop_status.setText("Fetching…")
        self._shop_table.setRowCount(0)

        self._shop_fetcher = _ShopFetcher(player, stat, sport, parent=self)
        self._shop_fetcher.finished.connect(self._on_shop_done)
        self._shop_fetcher.error.connect(lambda e: self._shop_status.setText(f"Error: {e}"))
        self._shop_fetcher.start()

    def _on_shop_done(self, pp_props: list, ud_props: list):
        all_rows = (
            [("PrizePicks", p) for p in pp_props] +
            [("Underdog",   p) for p in ud_props]
        )

        if not all_rows:
            self._shop_status.setText("No matching props found on either platform.")
            return

        self._shop_status.setText(
            f"Found {len(pp_props)} PrizePicks · {len(ud_props)} Underdog"
        )

        _COLORS = {"PrizePicks": ACCENT2, "Underdog": CYAN}

        self._shop_table.setRowCount(len(all_rows))
        for row, (platform, prop) in enumerate(all_rows):
            center = Qt.AlignmentFlag.AlignCenter

            def _item(t, a=Qt.AlignmentFlag.AlignLeft):
                i = QTableWidgetItem(str(t))
                i.setTextAlignment(a | Qt.AlignmentFlag.AlignVCenter)
                return i

            p_item = _item(platform, center)
            p_item.setForeground(QColor(_COLORS.get(platform, ACCENT)))
            self._shop_table.setItem(row, 0, p_item)
            self._shop_table.setItem(row, 1, _item(prop["stat"]))
            self._shop_table.setItem(row, 2, _item(
                f"{prop['line']:.1f}" if prop["line"] else "—", center
            ))
            self._shop_table.setItem(row, 3, _item(
                f"{prop['trending_count']:,}", center
            ))

        self._shop_table.resizeColumnToContents(0)
        self._shop_table.resizeColumnToContents(2)
        self._shop_table.resizeColumnToContents(3)

    # ── Prop Analysis ─────────────────────────────────────────────────────────

    def _build_prop_panel(self) -> QWidget:
        group = QGroupBox("Single Prop Analysis")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(10)

        fields = QFormLayout()
        fields.setSpacing(8)
        fields.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._pa_player  = QLineEdit()
        self._pa_player.setPlaceholderText("Player name")

        self._pa_team    = QLineEdit()
        self._pa_team.setPlaceholderText("Team abbreviation")

        self._pa_sport   = QComboBox()
        self._pa_sport.addItems(["NBA", "WNBA", "NFL", "MLB"])

        self._pa_stat    = QComboBox()
        for st in StatType:
            self._pa_stat.addItem(st.value, userData=st)

        self._pa_line    = QDoubleSpinBox()
        self._pa_line.setRange(0, 1000)
        self._pa_line.setDecimals(1)
        self._pa_line.setValue(20.5)

        self._pa_proj    = QDoubleSpinBox()
        self._pa_proj.setRange(0, 1000)
        self._pa_proj.setDecimals(1)
        self._pa_proj.setValue(23.0)

        # Form weighting inputs
        self._pa_season_avg = QDoubleSpinBox()
        self._pa_season_avg.setRange(0, 1000)
        self._pa_season_avg.setDecimals(1)
        self._pa_season_avg.setSpecialValueText("—")

        self._pa_recent_avg = QDoubleSpinBox()
        self._pa_recent_avg.setRange(0, 1000)
        self._pa_recent_avg.setDecimals(1)
        self._pa_recent_avg.setSpecialValueText("—")

        fields.addRow("Player",          self._pa_player)
        fields.addRow("Team",            self._pa_team)
        fields.addRow("Sport",           self._pa_sport)
        fields.addRow("Stat",            self._pa_stat)
        fields.addRow("Line",            self._pa_line)
        fields.addRow("Your Projection", self._pa_proj)
        fields.addRow("Season Avg (opt)",self._pa_season_avg)
        fields.addRow("Last 5 Avg (opt)",self._pa_recent_avg)

        layout.addLayout(fields)

        analyze_btn = QPushButton("Analyze Prop")
        analyze_btn.clicked.connect(self._run_prop_analysis)
        layout.addWidget(analyze_btn)

        # Result card
        self._pa_result = QFrame()
        self._pa_result.setObjectName("card")
        self._pa_result.hide()
        rl = QVBoxLayout(self._pa_result)
        rl.setContentsMargins(12, 12, 12, 12)
        rl.setSpacing(6)

        self._pa_grade     = QLabel()
        self._pa_grade.setStyleSheet("font-size: 28px; font-weight: 700;")
        self._pa_grade.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._pa_action    = QLabel()
        self._pa_action.setStyleSheet("font-size: 13px; font-weight: 600;")
        self._pa_action.setAlignment(Qt.AlignmentFlag.AlignCenter)

        rows = QFormLayout()
        rows.setSpacing(5)
        self._pa_edge_lbl  = QLabel()
        self._pa_conf_lbl  = QLabel()
        self._pa_dir_lbl   = QLabel()
        self._pa_proj_lbl  = QLabel()   # weighted projection
        self._pa_form_lbl  = QLabel()   # form signal

        rows.addRow("Edge:",              self._pa_edge_lbl)
        rows.addRow("Confidence:",        self._pa_conf_lbl)
        rows.addRow("Direction:",         self._pa_dir_lbl)
        rows.addRow("Weighted Proj:",     self._pa_proj_lbl)
        rows.addRow("Form:",              self._pa_form_lbl)

        rl.addWidget(self._pa_grade)
        rl.addWidget(self._pa_action)
        rl.addLayout(rows)
        layout.addWidget(self._pa_result)
        layout.addStretch()
        return group

    def _run_prop_analysis(self):
        player_name  = self._pa_player.text().strip() or "Player"
        team         = self._pa_team.text().strip() or "—"
        sport        = self._pa_sport.currentText()
        stat         = self._pa_stat.currentData()
        line         = self._pa_line.value()
        projection   = self._pa_proj.value()
        season_avg   = self._pa_season_avg.value()
        recent_avg   = self._pa_recent_avg.value()

        # Apply form weighting if both averages provided
        use_form = season_avg > 0 and recent_avg > 0
        if use_form:
            adj_proj = weighted_projection(season_avg, recent_avg)
            fsignal  = form_signal(recent_avg, season_avg)
        else:
            adj_proj = projection
            fsignal  = "—"

        edge = calculate_edge(line, adj_proj)
        conf = calculate_confidence(edge)

        prop = Prop(
            player=Player(name=player_name, team=team, sport=sport),
            stat=stat,
            line=line,
            projection=adj_proj,
            edge=edge,
            confidence=conf,
        )
        result = prop_recommendation(prop)
        grade = result["grade"]
        action = result["action"]
        color = {
            "green": GREEN,
            "yellow": YELLOW,
            "red": RED,
        }.get(result["color"], ACCENT)

        direction = "OVER" if edge > 0 else ("UNDER" if edge < 0 else "EVEN")

        self._pa_grade.setText(grade)
        self._pa_grade.setStyleSheet(f"font-size: 28px; font-weight: 700; color: {color};")
        self._pa_action.setText(action)
        self._pa_action.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {color};")
        self._pa_edge_lbl.setText(f"{edge:+.1f}")
        self._pa_conf_lbl.setText(f"{conf:.0f}%")
        self._pa_dir_lbl.setText(direction)
        self._pa_dir_lbl.setStyleSheet(f"color: {color}; font-weight: 700;")
        self._pa_proj_lbl.setText(f"{adj_proj:.1f}" + (" (form-adjusted)" if use_form else " (manual)"))
        self._pa_form_lbl.setText(fsignal)
        self._pa_result.show()
