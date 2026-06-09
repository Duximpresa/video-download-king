from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


STYLE = """
QMainWindow, QWidget { background: #f5f7fa; color: #1f2937; }
QGroupBox { font-weight: 600; border: 1px solid #d8dee8; border-radius: 8px; margin-top: 10px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTableWidget {
    background: white; border: 1px solid #cfd6e1; border-radius: 5px; padding: 5px;
}
QPushButton { background: #2563eb; color: white; border: 0; border-radius: 5px; padding: 7px 14px; }
QPushButton:hover { background: #1d4ed8; }
QPushButton:disabled { background: #aab4c3; }
QProgressBar { border: 1px solid #cfd6e1; border-radius: 5px; text-align: center; background: white; }
QProgressBar::chunk { background: #22c55e; border-radius: 4px; }
"""


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Video Download King")
    app.setOrganizationName("Video Download King")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    return app.exec()

