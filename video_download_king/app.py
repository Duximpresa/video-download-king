from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


STYLE = """
QMainWindow, QWidget { background: #f5f7fa; color: #1f2937; font-size: 12px; }
QGroupBox {
    font-weight: 600; border: 1px solid #d8dee8; border-radius: 6px;
    margin-top: 7px; padding-top: 7px;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTableWidget {
    background: white; border: 1px solid #cfd6e1; border-radius: 4px;
}
QLineEdit, QComboBox, QSpinBox {
    min-height: 20px; max-height: 24px; padding: 1px 5px;
}
QCheckBox { spacing: 6px; min-height: 20px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #64748b; border-radius: 3px; background: white; }
QCheckBox::indicator:hover { border-color: #2563eb; }
QCheckBox::indicator:checked { background: #2563eb; border-color: #1d4ed8; image: url("__CHECK_ICON__"); }
QTableWidget { gridline-color: #dbe3ee; alternate-background-color: #f1f5f9; selection-background-color: #174ea6; selection-color: white; }
QTableWidget::item { padding: 3px 5px; }
QTableWidget::item:hover { background: #dbeafe; color: #172554; }
QTableWidget::item:selected { background: #174ea6; color: white; border-top: 1px solid #0f3d86; border-bottom: 1px solid #0f3d86; }
QPushButton {
    background: #2563eb; color: white; border: 0; border-radius: 4px;
    min-width: 0; min-height: 20px; padding: 3px 9px;
}
QPushButton:hover { background: #1d4ed8; }
QPushButton:disabled { background: #aab4c3; }
QPushButton[secondary="true"] { background: #64748b; }
QPushButton[secondary="true"]:hover { background: #475569; }
QPushButton[danger="true"] { background: #dc2626; }
QPushButton[danger="true"]:hover { background: #b91c1c; }
QProgressBar {
    border: 1px solid #cfd6e1; border-radius: 4px; text-align: center;
    background: white; min-height: 18px; max-height: 20px;
}
QProgressBar::chunk { background: #22c55e; border-radius: 3px; }
"""


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Video Download King")
    app.setOrganizationName("Video Download King")
    assets_dir = Path(__file__).resolve().parent / "assets"
    app.setWindowIcon(QIcon(str(assets_dir / "logo-512.png")))
    check_icon = (assets_dir / "check.svg").as_posix()
    app.setStyleSheet(STYLE.replace("__CHECK_ICON__", check_icon))
    window = MainWindow()
    window.setWindowIcon(app.windowIcon())
    window.show()
    window.start_hardware_detection()
    return app.exec()
