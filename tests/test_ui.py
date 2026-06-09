from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QSpinBox

from video_download_king.config import AppSettings
from video_download_king.main_window import MainWindow
from video_download_king.settings_dialog import SettingsDialog


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_all_numeric_inputs_hide_step_buttons(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    dialog = SettingsDialog(AppSettings())
    spin_boxes = window.findChildren(QSpinBox) + dialog.findChildren(QSpinBox)
    assert spin_boxes
    assert all(box.buttonSymbols() == QSpinBox.NoButtons for box in spin_boxes)
    assert window.findChildren(QComboBox)
    window.close()
    dialog.close()


def test_cover_mode_disables_media_controls(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("cover"))
    assert not window.format_panel.isEnabled()
    assert not window.transcode_panel.isEnabled()
    assert not window.download_subtitles_check.isEnabled()
    assert window.filename_template.isEnabled()
    window.close()
