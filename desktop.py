"""
EdgeIQ Desktop — entry point.

Run with:
    python desktop.py
"""

import sys
from PyQt6.QtWidgets import QApplication
from gui.app import EdgeIQWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("EdgeIQ")
    window = EdgeIQWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
