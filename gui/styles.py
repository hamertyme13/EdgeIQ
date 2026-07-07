"""
Shared PyQt6 stylesheet and color constants for EdgeIQ desktop.
"""

# ── Palette ──────────────────────────────────────────────────────────────────
BG         = "#0f1117"
SURFACE    = "#1a1d27"
SURFACE2   = "#21253a"
BORDER     = "#2e3247"
TEXT       = "#e8eaf0"
MUTED      = "#7a7f9a"
ACCENT     = "#4f8ef7"
ACCENT2    = "#7c5cd8"
GREEN      = "#22c55e"
YELLOW     = "#f59e0b"
RED        = "#ef4444"
CYAN       = "#06b6d4"

APP_STYLESHEET = f"""
/* ── Base ─────────────────────────────────────────── */
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
}}

/* ── Main window & frames ─────────────────────────── */
QMainWindow, QDialog {{
    background-color: {BG};
}}

QFrame#card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

/* ── Tab bar ──────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background-color: {SURFACE};
}}

QTabBar::tab {{
    background-color: {BG};
    color: {MUTED};
    padding: 9px 22px;
    border: 1px solid transparent;
    border-bottom: none;
    margin-right: 2px;
    font-size: 13px;
}}

QTabBar::tab:selected {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-bottom: 1px solid {SURFACE};
}}

QTabBar::tab:hover:!selected {{
    color: {TEXT};
}}

/* ── Buttons ──────────────────────────────────────── */
QPushButton {{
    background-color: {ACCENT};
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: #3a7de8;
}}

QPushButton:pressed {{
    background-color: #2d6cd4;
}}

QPushButton#secondary {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid {BORDER};
}}

QPushButton#secondary:hover {{
    background-color: {BORDER};
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
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 10px;
    font-size: 13px;
    min-height: 20px;
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
}}

/* ── Tables ───────────────────────────────────────── */
QTableWidget {{
    background-color: {SURFACE};
    alternate-background-color: {SURFACE2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
    color: {TEXT};
}}

QTableWidget::item {{
    padding: 6px 10px;
}}

QTableWidget::item:selected {{
    background-color: {ACCENT};
    color: #ffffff;
}}

QHeaderView::section {{
    background-color: {SURFACE2};
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
    background-color: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {MUTED};
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
    background-color: {BORDER};
    border-radius: 4px;
    min-width: 24px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {MUTED};
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
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
    color: {MUTED};
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    top: -6px;
    padding: 0 6px;
    background-color: {BG};
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
