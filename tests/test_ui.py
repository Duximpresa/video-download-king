from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
)

from video_download_king.config import AppSettings
from video_download_king.config import SettingsStore
from video_download_king.app import STYLE
from video_download_king.bilibili_page import BilibiliPage
from video_download_king.douyin_page import DouyinPage
from video_download_king.xiaohongshu_page import XiaohongshuPage
from video_download_king.main_window import MainWindow
from video_download_king.models import SubtitleInfo, TaskResult
from video_download_king.settings_dialog import SettingsDialog
from video_download_king.subtitle_dialog import SubtitleDialog
from video_download_king.models import (
    DouyinAsset,
    DouyinMediaInfo,
    TranscodeConfig,
    XiaohongshuAsset,
    XiaohongshuMediaInfo,
)
from video_download_king.transcode_panel import TranscodePanel


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_xiaohongshu_tabs_follow_bilibili(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    main_tabs = window.centralWidget()
    assert [main_tabs.tabText(i) for i in range(main_tabs.count())] == [
        "单链接下载", "抖音下载", "B站下载", "小红书下载", "批量下载"
    ]
    dialog = SettingsDialog(AppSettings())
    settings_tabs = dialog.findChild(QTabWidget)
    assert [settings_tabs.tabText(i) for i in range(settings_tabs.count())] == [
        "代理", "YouTube / Instagram / TikTok / X 登录", "抖音登录", "B站登录", "小红书登录", "网络"
    ]
    assert "TikTok" in window.url_edit.placeholderText()


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
    assert window.format_panel.isEnabled()
    assert window.mode_combo.isEnabled()
    assert not window.quality_combo.isEnabled()
    assert not window.format_tabs.isEnabled()
    assert not window.transcode_panel.isEnabled()
    assert not window.subtitle_button.isEnabled()
    assert window.filename_template.isEnabled()
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("video_audio"))
    assert window.transcode_panel.isEnabled()
    assert window.quality_combo.isEnabled()
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


def test_analysis_has_dedicated_stop_button(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    cancelled: list[bool] = []
    window.cancel_requested.connect(lambda: cancelled.append(True))
    window.worker = object()
    window._analysis_running = True
    window._set_busy(True, "正在分析链接...")
    assert not window.stop_analysis_button.isHidden()
    assert window.stop_analysis_button.isEnabled()
    window.stop_analysis_button.click()
    assert cancelled == [True]
    assert not window.stop_analysis_button.isEnabled()
    window.worker = None
    window._analysis_running = False
    window._set_busy(False, "分析已取消")
    assert window.stop_analysis_button.isHidden()
    window.close()


def test_douyin_analysis_has_dedicated_stop_button(tmp_path: Path) -> None:
    app()
    page = DouyinPage(AppSettings(save_path=str(tmp_path)), SettingsStore(tmp_path / "settings.json"))
    cancelled: list[bool] = []
    page.cancel_requested.connect(lambda: cancelled.append(True))
    page.worker = object()
    page._analysis_running = True
    page._set_busy(True, "正在分析抖音作品...")
    assert not page.stop_analysis_button.isHidden()
    page.stop_analysis_button.click()
    assert cancelled == [True]
    page.worker = None
    page._analysis_running = False
    page._set_busy(False, "分析已取消")
    assert page.stop_analysis_button.isHidden()
    page.close()


def test_settings_proxy_tab_has_custom_connectivity_test() -> None:
    app()
    dialog = SettingsDialog(AppSettings())
    assert dialog.test_url.text() == "https://www.google.com/"
    assert isinstance(dialog.test_url, QLineEdit)
    assert dialog.test_button.text() == "测试网络连通性"
    assert "无需先保存" in dialog.test_result.text()
    dialog.close()


def test_all_download_url_fields_have_clear_and_replace_paste(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    pages = [window, window.douyin_page, window.bilibili_page, window.xiaohongshu_page]
    for page in pages:
        page.url_edit.setText("old value")
        page.clear_url_button.click()
        assert page.url_edit.text() == ""
        QApplication.clipboard().setText("new clipboard value")
        page.url_edit.setText("replace me")
        page.paste_url_button.click()
        assert page.url_edit.text() == "new clipboard value"
        QApplication.clipboard().setText("")
        page.paste_url_button.click()
        assert page.url_edit.text() == ""
    dialog = SettingsDialog(AppSettings())
    assert not hasattr(dialog, "clear_test_url_button")
    assert not hasattr(dialog, "paste_test_url_button")
    dialog.close()
    window.close()


def test_cookie_clear_buttons_only_persist_when_applied() -> None:
    app()
    settings = AppSettings(
        cookie_file="common.txt",
        cookie_browser="chrome",
        douyin_cookie_file="douyin.txt",
        bilibili_cookie_file="bilibili.txt",
        xiaohongshu_cookie_file="xiaohongshu.txt",
    )
    dialog = SettingsDialog(settings)
    for button in (
        dialog.clear_cookie_button,
        dialog.clear_douyin_cookie_button,
        dialog.clear_bilibili_cookie_button,
        dialog.clear_xiaohongshu_cookie_button,
    ):
        button.click()
    assert settings.cookie_file == "common.txt"
    assert settings.douyin_cookie_file == "douyin.txt"
    dialog.reject()

    saved_dialog = SettingsDialog(settings)
    saved_dialog.clear_cookie_button.click()
    saved_dialog.clear_douyin_cookie_button.click()
    saved_dialog.clear_bilibili_cookie_button.click()
    saved_dialog.clear_xiaohongshu_cookie_button.click()
    saved_dialog.apply(settings)
    assert settings.cookie_file == ""
    assert settings.douyin_cookie_file == ""
    assert settings.bilibili_cookie_file == ""
    assert settings.xiaohongshu_cookie_file == ""
    assert settings.cookie_browser == "chrome"
    saved_dialog.close()


def test_platform_cookie_request_priority(tmp_path: Path) -> None:
    app()
    settings = AppSettings(
        save_path=str(tmp_path),
        cookie_file="common.txt",
        douyin_cookie_file="douyin.txt",
        bilibili_cookie_file="bilibili.txt",
        xiaohongshu_cookie_file="xiaohongshu.txt",
    )
    store = SettingsStore(tmp_path / "settings.json")
    douyin = DouyinPage(settings, store)
    xhs = XiaohongshuPage(settings, store)
    bili = BilibiliPage(settings, store)
    cases = [
        (douyin, "https://www.douyin.com/video/7604129988555574538", "douyin_cookie_file", "douyin.txt"),
        (bili, "https://www.bilibili.com/video/BV1Ab411c7mD", "bilibili_cookie_file", "bilibili.txt"),
        (xhs, "https://www.xiaohongshu.com/explore/65abcdef0000000012345678", "xiaohongshu_cookie_file", "xiaohongshu.txt"),
    ]
    for page, url, field, specific in cases:
        page.url_edit.setText(url)
        assert page._request().cookie_file == specific
        setattr(settings, field, "")
        assert page._request().cookie_file == "common.txt"
        settings.cookie_file = ""
        assert page._request().cookie_file == ""
        settings.cookie_file = "common.txt"
        setattr(settings, field, specific)
        page.close()


def test_success_completion_uses_logs_without_information_popup(monkeypatch, tmp_path: Path) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    monkeypatch.setattr(
        "video_download_king.main_window.QMessageBox.information",
        lambda *args, **kwargs: pytest.fail("success popup must not be shown"),
    )
    window = MainWindow()
    output = tmp_path / "saved.mp4"
    result = TaskResult(True, "完成", output, [output])
    pages_and_callbacks = [
        (window, window._download_complete),
        (window.douyin_page, window.douyin_page._download_complete),
        (window.bilibili_page, window.bilibili_page._complete),
        (window.xiaohongshu_page, window.xiaohongshu_page._complete),
    ]
    for page, callback in pages_and_callbacks:
        callback(result)
        log = page.log.toPlainText()
        assert "下载完成" in log
        assert str(output) in log
    window.close()


def test_open_folder_tracks_latest_successful_output_directory(monkeypatch, tmp_path: Path) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    opened: list[Path] = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda url: opened.append(Path(url.toLocalFile())),
    )
    window = MainWindow()
    pages_and_callbacks = [
        (window, window._download_complete),
        (window.douyin_page, window.douyin_page._download_complete),
        (window.bilibili_page, window.bilibili_page._complete),
        (window.xiaohongshu_page, window.xiaohongshu_page._complete),
    ]

    configured_roots: list[Path] = []
    for index, (page, _callback) in enumerate(pages_and_callbacks):
        configured_root = tmp_path / f"configured-{index}"
        configured_roots.append(configured_root)
        page.path_edit.setText(str(configured_root))
        page._open_output()
        assert opened[-1] == configured_root.resolve()
        assert configured_root.is_dir()

    actual_dir = tmp_path / "Instagram" / "author"
    actual_dir.mkdir(parents=True)
    output = actual_dir / "video.mp4"
    output.touch()
    result = TaskResult(True, "完成", output, [output])
    for page, callback in pages_and_callbacks:
        callback(result)
        page._open_output()
        assert opened[-1] == actual_dir.resolve()

    cancelled = TaskResult(False, "任务已取消", error_category="已取消")
    for page, callback in pages_and_callbacks:
        callback(cancelled)
        page._open_output()
        assert opened[-1] == actual_dir.resolve()

    output.unlink()
    actual_dir.rmdir()
    shared_root = configured_roots[-1]
    for page, _callback in pages_and_callbacks:
        page._open_output()
        assert opened[-1] == shared_root.resolve()
    window.close()


def test_all_download_pages_share_and_persist_one_save_path(monkeypatch, tmp_path: Path) -> None:
    app()
    store = SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr("video_download_king.main_window.SettingsStore", lambda: store)
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    path_edits = [
        window.path_edit,
        window.douyin_page.path_edit,
        window.bilibili_page.path_edit,
        window.xiaohongshu_page.path_edit,
    ]

    first_path = str(tmp_path / "统一下载目录")
    window.douyin_page.path_edit.setText(first_path)
    assert all(path_edit.text() == first_path for path_edit in path_edits)
    assert window.settings.save_path == first_path
    window.douyin_page.path_edit.editingFinished.emit()
    assert store.load().save_path == first_path

    second_path = str(tmp_path / "B站修改后的目录")
    window.bilibili_page.path_edit.setText(second_path)
    assert all(path_edit.text() == second_path for path_edit in path_edits)
    window.bilibili_page.path_edit.editingFinished.emit()
    assert store.load().save_path == second_path
    window.close()


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
    assert window.encoding_scroll in scroll_areas
    assert window.status_panel.minimumHeight() >= 150
    assert window.minimumSize().width() <= 1024
    assert window.minimumSize().height() <= 720
    assert window.video_table.minimumHeight() <= 260
    assert window.audio_table.minimumHeight() <= 260
    window.close()


def test_pages_follow_viewport_after_widening_and_shrinking(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    window.show()
    QApplication.processEvents()
    tabs = window.centralWidget()
    for index in (0, 1, 2, 3):
        tabs.setCurrentIndex(index)
        QApplication.processEvents()
        window.resize(1600, 760)
        QApplication.processEvents()
        window.resize(1024, 680)
        QApplication.processEvents()
        if index == 0:
            assert not isinstance(tabs.widget(index), QScrollArea)
            assert window.encoding_scroll.horizontalScrollBar().maximum() == 0
            assert window.status_panel.height() >= window.status_panel.minimumHeight()
        else:
            scroll = tabs.widget(index)
            assert isinstance(scroll, QScrollArea)
            assert scroll.widget().width() == scroll.viewport().width()
            assert scroll.horizontalScrollBar().maximum() == 0
        analyze = (
            window.analyze_button
            if index == 0
            else window.douyin_page.analyze_button
            if index == 1
            else window.bilibili_page.analyze_button
            if index == 2
            else window.xiaohongshu_page.analyze_button
        )
        assert analyze.isVisible()
    window.close()


def test_combo_box_style_keeps_native_drop_down_arrow() -> None:
    assert "QComboBox::drop-down" not in STYLE


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
    window.close()


def test_douyin_analysis_lists_actual_native_video_versions(tmp_path: Path) -> None:
    app()
    page = DouyinPage(AppSettings(save_path=str(tmp_path)), SettingsStore(tmp_path / "settings.json"))
    page.url_edit.setText("https://www.douyin.com/video/7604129988555574538")
    page._analysis_complete(
        DouyinMediaInfo(
            "https://www.douyin.com/video/7604129988555574538",
            "7604129988555574538",
            "测试视频",
            video_assets=[
                DouyinAsset("video", ("low",), width=960, height=540, bitrate=500_000, codec="normal_540_0"),
                DouyinAsset("video", ("high",), width=1920, height=1080, bitrate=2_000_000, codec="normal_1080_0"),
            ],
        )
    )
    assert page.quality_combo.count() == 2
    assert page.quality_combo.currentData() == "asset:1"
    assert "1080p" in page.quality_combo.currentText()
    assert "2.00 Mbps" in page.quality_combo.currentText()
    assert page.quality_combo.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert page._request().quality == "asset:1"

    page.engine_combo.setCurrentIndex(page.engine_combo.findData("yt_dlp"))
    assert page.quality_combo.findData("highest") >= 0
    page.close()


def test_xiaohongshu_analysis_lists_actual_video_versions(tmp_path: Path) -> None:
    app()
    page = XiaohongshuPage(
        AppSettings(save_path=str(tmp_path)), SettingsStore(tmp_path / "settings.json")
    )
    page.url_edit.setText("https://www.xiaohongshu.com/explore/65abcdef0000000012345678")
    page._analysis_complete(
        XiaohongshuMediaInfo(
            "https://www.xiaohongshu.com/explore/65abcdef0000000012345678",
            "65abcdef0000000012345678",
            "测试视频",
            video_assets=[
                XiaohongshuAsset(
                    "video", ("low",), width=720, height=480, bitrate=900, codec="h264"
                ),
                XiaohongshuAsset(
                    "video", ("high",), width=1920, height=1080, bitrate=2000, codec="h264"
                ),
            ],
        )
    )
    assert page.video_preference.count() == 2
    assert page.video_preference.currentData() == "asset:1"
    assert "1920×1080" in page.video_preference.currentText()
    assert "2.00 Mbps" in page.video_preference.currentText()
    page.video_preference.setCurrentIndex(page.video_preference.findData("asset:0"))
    assert page._request().video_preference == "asset:0"
    page.close()


def test_transcode_panel_exists_only_on_single_download_page(monkeypatch) -> None:
    app()
    monkeypatch.setattr(
        "video_download_king.main_window.FFmpegService.detect_encoders",
        lambda self, on_log=None: {"nvidia": False, "intel": False, "amd": False},
    )
    window = MainWindow()
    assert isinstance(window.transcode_panel, TranscodePanel)
    assert not window.transcode_panel.compact
    assert not hasattr(window.douyin_page, "transcode_panel")
    assert isinstance(window.xiaohongshu_page, XiaohongshuPage)
    assert not hasattr(window.xiaohongshu_page, "transcode_panel")
    assert not hasattr(window.xiaohongshu_page, "engine_combo")
    assert not hasattr(window.bilibili_page, "transcode_panel")
    window.close()


def test_transcode_panel_section_order_and_mode_linking() -> None:
    app()
    panel = TranscodePanel()
    assert [
        panel.image_group.title(),
        panel.bitrate_group.title(),
        panel.audio_group.title(),
        panel.hardware_group.title(),
        panel.output_group.title(),
    ] == ["图像", "比特率调整", "音频设置", "硬件加速", "文件与输出选项"]

    panel.rate_mode.setCurrentIndex(panel.rate_mode.findData("cq"))
    assert panel.video_bitrate_label.text() == "值"
    assert panel.video_bitrate_combo.findText("最好") >= 0
    assert not panel.two_pass_check.isEnabled()
    assert not panel.file_size_edit.isEnabled()

    panel.rate_mode.setCurrentIndex(panel.rate_mode.findData("vbr"))
    assert panel.video_bitrate_label.text() == "视频比特率"
    assert panel.video_bitrate_combo.findText("auto") >= 0
    assert panel.two_pass_check.isEnabled()

    panel.scale_combo.setCurrentText("1920x1080")
    panel.portrait_check.setChecked(True)
    assert panel.scale_combo.currentText() == "1080x1920"
    panel.close()


def test_hardware_controls_disable_unavailable_backends() -> None:
    app()
    panel = TranscodePanel()
    panel.set_available_hardware(
        {
            "nvidia": True,
            "intel": False,
            "amd": False,
            "decode_cuda": True,
            "filter_cuda": True,
        }
    )
    nvidia = panel.video_encoder_combo.model().item(
        panel.video_encoder_combo.findData("nvidia")
    )
    intel = panel.video_encoder_combo.model().item(
        panel.video_encoder_combo.findData("intel")
    )
    assert nvidia.isEnabled()
    assert not intel.isEnabled()
    panel.close()


def test_douyin_requests_never_enable_transcoding(tmp_path: Path) -> None:
    app()
    store = SettingsStore(tmp_path / "settings.json")
    settings = AppSettings(
        save_path=str(tmp_path),
        transcode=TranscodeConfig(enabled=True),
    )
    page = DouyinPage(settings, store)
    page.url_edit.setText("https://www.douyin.com/video/7604129988555574538")
    assert not page._request().transcode.enabled
    assert settings.transcode.enabled
    page.close()


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
