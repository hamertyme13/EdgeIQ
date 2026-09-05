"""
EdgeIQ Desktop — entry point.

Run with:
    python desktop.py
"""

import sys

from PyQt6.QtWidgets import QApplication

from config import APP_NAME, APP_VERSION
from gui.app import EdgeIQWindow
from utils.logging_config import configure_logging


def main():
    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    window = EdgeIQWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
