"""
Shared PyQt6 stylesheet and color constants for EdgeIQ desktop.
"""

# ── Rogue Circuit palette ────────────────────────────────────────────────────
BG         = "#05060d"
SURFACE    = "#0a0d16"
SURFACE2   = "#101522"
BORDER     = "#203041"
TEXT       = "#ededed"
MUTED      = "#8b98aa"
ACCENT     = "#39ff88"
ACCENT2    = "#7c3cff"
GREEN      = "#39ff88"
YELLOW     = "#f8c14a"
RED        = "#ff4d6d"
CYAN       = "#19e6ff"
SOFT_GREEN = "#102f25"
SOFT_CYAN  = "#0c2a35"
SOFT_VIOLET = "#1a1238"

APP_STYLESHEET = f"""
/* ── Base ─────────────────────────────────────────── */
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: Arial;
    font-size: 13px;
}}

QLabel {{
    background: transparent;
}}

/* ── Main window & frames ─────────────────────────── */
QMainWindow, QDialog {{
    background-color: {BG};
}}

QFrame#card {{
    background-color: {SURFACE};
    border: 1px solid #26384b;
    border-radius: 8px;
}}

/* ── Tab bar ──────────────────────────────────────── */
QTabWidget::pane {{
    border: none;
    background-color: {BG};
}}

QTabBar {{
    background-color: {BG};
}}

QTabBar::tab {{
    background-color: transparent;
    color: {MUTED};
    padding: 10px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 4px;
    font-size: 13px;
}}

QTabBar::tab:selected {{
    background-color: transparent;
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}

QTabBar::tab:hover:!selected {{
    color: {TEXT};
}}

/* ── Buttons ──────────────────────────────────────── */
QPushButton {{
    background-color: {ACCENT};
    color: {BG};
    border: none;
    border-radius: 5px;
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: #70ffab;
}}

QPushButton:pressed {{
    background-color: #20d96e;
}}

QPushButton#secondary {{
    background-color: {SOFT_CYAN};
    color: {TEXT};
    border: 1px solid #23596a;
}}

QPushButton#secondary:hover {{
    background-color: #123847;
    border-color: {CYAN};
}}

QPushButton#danger {{
    background-color: {RED};
}}

QPushButton#danger:hover {{
    background-color: #dc2626;
}}

/* ── Inputs ───────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid #24374a;
    border-radius: 5px;
    padding: 5px 9px;
    font-size: 13px;
    min-height: 20px;
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {CYAN};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {SOFT_CYAN};
}}

/* ── Tables ───────────────────────────────────────── */
QTableWidget {{
    background-color: {SURFACE};
    alternate-background-color: #0d1320;
    border: 1px solid #24374a;
    border-radius: 6px;
    gridline-color: {BORDER};
    color: {TEXT};
}}

QTableWidget::item {{
    padding: 5px 8px;
}}

QTableWidget::item:selected {{
    background-color: {SOFT_CYAN};
    color: {TEXT};
}}

QHeaderView::section {{
    background-color: #101827;
    color: {MUTED};
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* ── Scroll bars ──────────────────────────────────── */
QScrollBar:vertical {{
    background-color: {BG};
    width: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background-color: #26384b;
    border-radius: 4px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {CYAN};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background-color: {BG};
    height: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal {{
    background-color: #26384b;
    border-radius: 4px;
    min-width: 24px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {CYAN};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Labels ───────────────────────────────────────── */
QLabel#section-title {{
    font-size: 16px;
    font-weight: 700;
    color: {TEXT};
}}

QLabel#stat-value {{
    font-size: 26px;
    font-weight: 700;
    color: {ACCENT};
}}

QLabel#stat-label {{
    font-size: 11px;
    color: {MUTED};
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

QLabel#muted {{
    color: {MUTED};
    font-size: 12px;
}}

/* ── Group box ────────────────────────────────────── */
QGroupBox {{
    border: 1px solid #24374a;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 8px;
    color: {MUTED};
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: -7px;
    padding: 1px 6px;
    background-color: {BG};
    color: {CYAN};
}}

/* ── Separator ────────────────────────────────────── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {BORDER};
}}

/* ── Status bar ───────────────────────────────────── */
QStatusBar {{
    background-color: {BG};
    color: {MUTED};
    font-size: 11px;
    border-top: 1px solid {BORDER};
}}
"""
