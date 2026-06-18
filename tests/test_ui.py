from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox

from video_download_king.config import AppSettings
from video_download_king.config import SettingsStore
from video_download_king.douyin_page import DouyinPage
from video_download_king.main_window import MainWindow
from video_download_king.models import SubtitleInfo
from video_download_king.settings_dialog import SettingsDialog
from video_download_king.subtitle_dialog import SubtitleDialog
from video_download_king.models import DouyinAsset, DouyinMediaInfo
from video_download_king.transcode_panel import TranscodePanel


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


def test_analysis_progress_is_indeterminate_and_cancel_is_enabled(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    window._set_busy(True, "正在分析链接...")
    window._set_analysis_progress()
    assert window.total_progress.maximum() == 0
    assert window.stage_progress.maximum() == 0
    assert window.cancel_button.isEnabled()
    window._reset_analysis_progress()
    assert window.total_progress.maximum() == 100
    assert window.stage_progress.maximum() == 100
    window.close()


def test_settings_proxy_tab_has_custom_connectivity_test() -> None:
    app()
    dialog = SettingsDialog(AppSettings())
    assert dialog.test_url.text() == "https://www.google.com/"
    assert isinstance(dialog.test_url, QLineEdit)
    assert dialog.test_button.text() == "测试网络连通性"
    assert "无需先保存" in dialog.test_result.text()
    dialog.close()


def test_main_window_pages_are_scrollable_and_720p_sized(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    scroll_areas = window.findChildren(QScrollArea)
    assert len(scroll_areas) >= 3
    assert all(area.widgetResizable() for area in scroll_areas)
    assert window.minimumSize().width() <= 1024
    assert window.minimumSize().height() <= 720
    assert window.video_table.minimumHeight() <= 260
    assert window.audio_table.minimumHeight() <= 260
    window.close()


def test_main_window_has_douyin_page_and_gallery_forces_native(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    page = window.douyin_page
    assert page.engine_combo.currentData() == "native"
    assert len(page.findChildren(QProgressBar)) == 2
    page._analysis_complete(
        DouyinMediaInfo(
            "https://www.douyin.com/note/1",
            "1",
            "图集",
            media_type="gallery",
            gallery_assets=[DouyinAsset("image", ("https://example.com/1.jpg",), index=1)],
        )
    )
    assert page.engine_combo.currentData() == "native"
    assert not page.engine_combo.isEnabled()
    assert not page.transcode_group.isEnabled()
    window.close()


def test_transcode_panel_is_shared_by_single_and_douyin_pages(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    assert isinstance(window.transcode_panel, TranscodePanel)
    assert isinstance(window.douyin_page.transcode_panel, TranscodePanel)
    window.close()


def test_douyin_author_classification_and_template_buttons(tmp_path: Path) -> None:
    app()
    settings = AppSettings(save_path=str(tmp_path), douyin_classify_by_author=True)
    page = DouyinPage(settings, SettingsStore(tmp_path / "settings.json"))
    page.url_edit.setText("https://www.douyin.com/video/7604129988555574538")
    page._analysis_complete(
        DouyinMediaInfo(
            "https://www.douyin.com/video/7604129988555574538",
            "7604129988555574538",
            "测试作品",
            author="作者",
        )
    )
    assert page.classify_author_check.isChecked()
    request = page._request()
    assert request.classify_by_author

    page.filename_template.clear()
    author_button = next(button for button in page.findChildren(QPushButton) if button.text() == "作者")
    author_button.click()
    page.filename_template.insert("-{type}-{index}-{asset}")
    page._update_preview()
    assert "作者" in page.preview_label.text()
    assert "01" in page.preview_label.text()
    page._save_settings()
    assert settings.douyin_classify_by_author
    page.close()


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
