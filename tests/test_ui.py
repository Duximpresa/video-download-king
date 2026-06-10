from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QProgressBar, QSpinBox

from video_download_king.config import AppSettings
from video_download_king.main_window import MainWindow
from video_download_king.models import SubtitleInfo
from video_download_king.settings_dialog import SettingsDialog
from video_download_king.subtitle_dialog import SubtitleDialog


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
    assert not window.subtitle_button.isEnabled()
    assert window.filename_template.isEnabled()
    window.close()


def test_main_window_has_two_progress_bars(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    assert window.total_progress is not window.stage_progress
    assert len(window.findChildren(QProgressBar)) >= 2
    window.close()


def test_subtitle_dialog_prioritizes_manual_for_same_language() -> None:
    app()
    dialog = SubtitleDialog(
        [
            SubtitleInfo("en", "English", "manual", ("vtt",)),
            SubtitleInfo("en", "English", "automatic", ("vtt",)),
            SubtitleInfo("fr", "French", "automatic", ("vtt",)),
        ],
        [],
        "srt",
        False,
    )
    manual = dialog.manual_group.child(0)
    automatic = dialog.auto_group.child(0)
    automatic.setCheckState(0, Qt.Checked)
    manual.setCheckState(0, Qt.Checked)
    assert manual.checkState(0) == Qt.Checked
    assert automatic.checkState(0) == Qt.Unchecked
    assert dialog.auto_group.child(1).isHidden()
    dialog.close()
