from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QPixmap, QResizeEvent
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
)

from .config import AppSettings, SettingsStore
from .cookie_status import inspect_cookie_status
from .douyin_page import DouyinPage
from .xiaohongshu_page import XiaohongshuPage
from .bilibili_page import BilibiliPage
from .naming_widgets import create_url_action_buttons, template_button_widget
from .formats import audio_formats, video_formats
from .models import (
    DownloadRequest,
    FormatInfo,
    MediaInfo,
    ProxyConfig,
    SubtitleSelection,
    TaskProgress,
    TaskResult,
)
from .paths import deno_path, ffmpeg_path, ffprobe_path, yt_dlp_path
from .platforms import proxy_recommended_platform
from .settings_dialog import SettingsDialog
from .subtitle_dialog import SubtitleDialog
from .transcode import FFmpegService
from .transcode_panel import TranscodePanel
from .thumbnail_preview import configure_preview_proxy, thumbnail_request
from .utils import human_size, render_filename_template
from .workers import AnalyzeWorker, DownloadWorker
from . import __version__


class MainWindow(QMainWindow):
    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.store = SettingsStore()
        self.first_run = not self.store.path.exists()
        self.settings = self.store.load()
        self.media: MediaInfo | None = None
        self.subtitle_selections: list[SubtitleSelection] = []
        self.thread: QThread | None = None
        self.worker = None
        self._analysis_running = False
        self._last_output_dir: Path | None = None
        self.network = QNetworkAccessManager(self)
        self._thumbnail_candidates: list[str] = []
        self._thumbnail_generation = 0

        self.hardware_availability = {"nvidia": False, "intel": False, "amd": False}
        self.setWindowTitle(f"Video Download King {__version__}")
        self.setMinimumSize(1024, 680)
        self.resize(1180, 760)
        self._build_menu()
        self._build_ui()
        self._apply_settings()
        self._bind_shared_save_path()
        self._check_runtime()
        self._detect_hardware()

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("设置")
        action = QAction("网络与平台登录...", self)
        action.triggered.connect(self._open_settings)
        menu.addAction(action)
        help_menu = self.menuBar().addMenu("帮助")
        about = QAction("关于", self)
        about.triggered.connect(
            lambda: QMessageBox.information(
                self,
                "关于",
                f"Video Download King {__version__}\n基于 yt-dlp 与 FFmpeg。",
            )
        )
        help_menu.addAction(about)

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._build_single_tab(), "单链接下载")
        self.douyin_page = DouyinPage(self.settings, self.store, self)
        tabs.addTab(self._make_scroll_page(self.douyin_page), "抖音下载")
        self.bilibili_page = BilibiliPage(self.settings, self.store, self)
        tabs.addTab(self._make_scroll_page(self.bilibili_page), "B站下载")
        self.xiaohongshu_page = XiaohongshuPage(self.settings, self.store, self)
        tabs.addTab(self._make_scroll_page(self.xiaohongshu_page), "小红书下载")
        tabs.addTab(self._make_scroll_page(self._build_batch_tab()), "批量下载")
        tabs.currentChanged.connect(lambda _index: self._sync_scroll_pages())
        self.setCentralWidget(tabs)
        self.statusBar().showMessage("就绪")

    @staticmethod
    def _make_scroll_page(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setMinimumSize(0, 0)
        return scroll

    def _sync_scroll_pages(self) -> None:
        for scroll in self.findChildren(QScrollArea):
            content = scroll.widget()
            if content:
                content.resize(scroll.viewport().width(), content.height())
                content.updateGeometry()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_scroll_pages()

    def _build_single_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 7, 8, 7)
        root.setSpacing(6)
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

        url_row = QGridLayout()
        url_row.setHorizontalSpacing(6)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("粘贴 YouTube、Instagram、TikTok 单视频或 X 单条帖子链接")
        self.clear_url_button, self.paste_url_button = create_url_action_buttons(self.url_edit)
        self.analyze_button = QPushButton("分析链接")
        self.analyze_button.clicked.connect(self._analyze)
        self.stop_analysis_button = QPushButton("停止分析")
        self.stop_analysis_button.setProperty("danger", True)
        self.stop_analysis_button.setVisible(False)
        self.stop_analysis_button.clicked.connect(self._cancel)
        url_row.addWidget(QLabel("网址"), 0, 0)
        url_row.addWidget(self.url_edit, 0, 1)
        url_row.addWidget(self.clear_url_button, 0, 2)
        url_row.addWidget(self.paste_url_button, 0, 3)
        url_row.addWidget(self.analyze_button, 0, 4)
        url_row.addWidget(self.stop_analysis_button, 0, 5)
        url_row.setColumnStretch(1, 1)
        top_layout.addLayout(url_row)

        path_row = QGridLayout()
        path_row.setHorizontalSpacing(6)
        self.path_edit = QLineEdit()
        browse = QPushButton("选择...")
        browse.clicked.connect(self._browse_output)
        self.classify_check = QCheckBox("按平台分类保存")
        path_row.addWidget(QLabel("保存到"), 0, 0)
        path_row.addWidget(self.path_edit, 0, 1)
        path_row.addWidget(browse, 0, 2)
        path_row.addWidget(self.classify_check, 0, 3)
        path_row.setColumnStretch(1, 1)
        top_layout.addLayout(path_row)

        info_group = QGroupBox("视频信息")
        info_layout = QHBoxLayout(info_group)
        self.thumbnail = QLabel("等待分析")
        self.thumbnail.setFixedSize(176, 99)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self.thumbnail.setStyleSheet("background:#20242b;border-radius:6px;color:#9aa4b2")
        self.title_label = QLabel("尚未分析链接")
        self.title_label.setWordWrap(True)
        self.meta_label = QLabel("")
        self.cookie_status_label = QLabel("Cookie：等待分析")
        self.cookie_status_label.setWordWrap(True)
        details = QVBoxLayout()
        details.addWidget(self.title_label)
        details.addWidget(self.meta_label)
        details.addWidget(self.cookie_status_label)
        details.addStretch()
        info_layout.addWidget(self.thumbnail)
        info_layout.addLayout(details, 1)
        top_layout.addWidget(info_group)
        top_layout.addWidget(self._build_download_options())
        root.addWidget(top)

        encoding_splitter = QSplitter(Qt.Horizontal)
        self.format_panel = self._build_format_panel()
        self.transcode_panel = self._build_transcode_panel()
        encoding_splitter.addWidget(self.format_panel)
        encoding_splitter.addWidget(self.transcode_panel)
        encoding_splitter.setSizes([700, 430])
        encoding_splitter.setChildrenCollapsible(False)
        encoding_splitter.setMinimumHeight(
            max(
                self.format_panel.minimumSizeHint().height(),
                self.transcode_panel.minimumSizeHint().height(),
            )
        )
        encoding_splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.encoding_scroll = QScrollArea()
        self.encoding_scroll.setWidget(encoding_splitter)
        self.encoding_scroll.setWidgetResizable(True)
        self.encoding_scroll.setFrameShape(QFrame.NoFrame)
        self.encoding_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.encoding_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._mode_changed()

        self.status_panel = QFrame()
        self.status_panel.setObjectName("statusPanel")
        self.status_panel.setMinimumHeight(150)
        status_layout = QVBoxLayout(self.status_panel)
        status_layout.setContentsMargins(0, 5, 0, 0)
        status_layout.setSpacing(5)
        controls = QGridLayout()
        controls.setHorizontalSpacing(6)
        self.download_button = QPushButton("开始下载")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._download)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setProperty("secondary", True)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        self.open_folder_button = QPushButton("打开保存目录")
        self.open_folder_button.setProperty("secondary", True)
        self.open_folder_button.clicked.connect(self._open_output)
        self.total_progress = QProgressBar()
        self.total_progress.setRange(0, 100)
        self.total_progress.setValue(0)
        self.total_progress.setFormat("总任务 %p%")
        self.stage_progress = QProgressBar()
        self.stage_progress.setRange(0, 100)
        self.stage_progress.setValue(0)
        self.stage_progress.setFormat("当前阶段 %p%")
        self.progress = self.total_progress
        controls.addWidget(self.download_button, 0, 0)
        controls.addWidget(self.cancel_button, 0, 1)
        controls.addWidget(self.open_folder_button, 0, 2)
        controls.addWidget(self.total_progress, 0, 3)
        controls.addWidget(self.stage_progress, 0, 4)
        controls.setColumnStretch(3, 1)
        controls.setColumnStretch(4, 1)
        status_layout.addLayout(controls)

        self.progress_label = QLabel("就绪")
        status_layout.addWidget(self.progress_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(80)
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText("分析、下载和转码日志会显示在这里")
        status_layout.addWidget(self.log, 1)

        self.workspace_splitter = QSplitter(Qt.Vertical)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(5)
        self.workspace_splitter.addWidget(self.encoding_scroll)
        self.workspace_splitter.addWidget(self.status_panel)
        self.workspace_splitter.setSizes([420, 180])
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 1)
        root.addWidget(self.workspace_splitter, 1)
        return page

    def _build_format_panel(self) -> QWidget:
        group = QGroupBox("输出与格式")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 7)
        layout.setSpacing(5)
        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("视频+音频", "video_audio")
        self.mode_combo.addItem("仅视频", "video_only")
        self.mode_combo.addItem("仅音频", "audio")
        self.mode_combo.addItem("仅封面", "cover")
        self.mode_combo.addItem("高级流组合", "advanced")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.quality_combo = QComboBox()
        for label, value in (
            ("最高画质", "best"),
            ("2160p", "2160p"),
            ("1440p", "1440p"),
            ("1080p", "1080p"),
            ("720p", "720p"),
            ("480p", "480p"),
            ("最低画质", "worst"),
            ("自定义最大高度", "custom"),
        ):
            self.quality_combo.addItem(label, value)
        self.custom_height = QSpinBox()
        self.custom_height.setButtonSymbols(QSpinBox.NoButtons)
        self.custom_height.setRange(144, 4320)
        self.custom_height.setValue(1080)
        self.custom_height.setSuffix(" p")
        self.audio_output = QComboBox()
        for label, value in (("保留原始音频", "original"), ("AAC", "aac"), ("M4A", "m4a"), ("MP3", "mp3")):
            self.audio_output.addItem(label, value)
        form.addRow("输出模式", self.mode_combo)
        form.addRow("画质预设", self.quality_combo)
        form.addRow("自定义高度", self.custom_height)
        form.addRow("音频格式", self.audio_output)
        layout.addLayout(form)

        self.format_tabs = QTabWidget()
        self.video_selection_label = QLabel("当前视频流：未选择")
        self.audio_selection_label = QLabel("当前音频流：未选择")
        selection_row = QHBoxLayout()
        selection_row.addWidget(self.video_selection_label)
        selection_row.addWidget(self.audio_selection_label)
        layout.addLayout(selection_row)
        self.video_table = self._new_format_table()
        self.audio_table = self._new_format_table()
        self.video_table.itemSelectionChanged.connect(self._update_stream_selection)
        self.audio_table.itemSelectionChanged.connect(self._update_stream_selection)
        self.format_tabs.addTab(self.video_table, "视频流")
        self.format_tabs.addTab(self.audio_table, "音频流")
        layout.addWidget(self.format_tabs, 1)
        return group

    def _build_download_options(self) -> QWidget:
        group = QGroupBox("下载选项")
        layout = QGridLayout(group)
        layout.setContentsMargins(8, 8, 8, 7)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        self.filename_template = QLineEdit("{title} [{id}]")
        self.filename_template.textChanged.connect(self._update_filename_preview)
        layout.addWidget(QLabel("命名模板"), 0, 0)
        layout.addWidget(self.filename_template, 0, 1, 1, 4)

        fields = template_button_widget(self.filename_template, (
            ("标题", "{title}"),
            ("ID", "{id}"),
            ("频道", "{channel}"),
            ("平台", "{platform}"),
            ("上传日期", "{upload_date}"),
            ("下载日期", "{download_date}"),
        ))
        layout.addWidget(fields, 1, 0, 1, 3)

        self.download_thumbnail_check = QCheckBox("下载封面")
        self.subtitle_button = QPushButton("选择字幕...")
        self.subtitle_button.setEnabled(False)
        self.subtitle_button.clicked.connect(self._select_subtitles)
        self.subtitle_summary = QLabel("未选择字幕")
        extras = QHBoxLayout()
        extras.addWidget(self.download_thumbnail_check)
        extras.addWidget(self.subtitle_button)
        extras.addWidget(self.subtitle_summary, 1)
        layout.addLayout(extras, 1, 3, 1, 2)

        self.filename_preview = QLabel("预览：等待分析")
        self.filename_preview.setWordWrap(True)
        layout.addWidget(self.filename_preview, 2, 0, 1, 5)
        layout.setColumnStretch(1, 1)
        return group

    @staticmethod
    def _new_format_table() -> QTableWidget:
        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels(["ID", "分辨率", "FPS", "HDR", "编码", "容器", "码率", "大小"])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setMinimumHeight(205)
        table.verticalHeader().setDefaultSectionSize(27)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _build_transcode_panel(self) -> QWidget:
        panel = TranscodePanel()
        self._bind_transcode_panel(panel)
        return panel

    def _bind_transcode_panel(self, panel: TranscodePanel) -> None:
        self.transcode_check = panel.transcode_check
        self.keep_source_check = panel.keep_source_check
        self.rate_mode = panel.rate_mode
        self.video_encoder_combo = panel.video_encoder_combo
        self.suffix_mode = panel.suffix_mode
        self.custom_suffix = panel.custom_suffix

    @staticmethod
    def _build_batch_tab() -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel("批量下载将在后续版本开放。\n该页面将复用单链接任务模型和下载服务。")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size:20px;color:#687386")
        layout.addWidget(label)
        return page

    def _apply_settings(self) -> None:
        self.path_edit.setText(str(self.settings.resolved_save_path))
        self.classify_check.setChecked(self.settings.classify_by_platform)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(self.settings.output_mode)))
        self.filename_template.setText(self.settings.filename_template)
        self.download_thumbnail_check.setChecked(self.settings.download_thumbnail)
        self.transcode_panel.load_config(self.settings.transcode)
        self._update_filename_preview()

    def _bind_shared_save_path(self) -> None:
        self._syncing_save_path = False
        self._save_path_edits = (
            self.path_edit,
            self.douyin_page.path_edit,
            self.bilibili_page.path_edit,
            self.xiaohongshu_page.path_edit,
        )
        for path_edit in self._save_path_edits:
            path_edit.textChanged.connect(
                lambda text, source=path_edit: self._shared_save_path_changed(source, text)
            )
            path_edit.editingFinished.connect(self._persist_shared_save_path)

    def _shared_save_path_changed(self, source: QLineEdit, text: str) -> None:
        if self._syncing_save_path:
            return
        self._syncing_save_path = True
        try:
            for path_edit in self._save_path_edits:
                if path_edit is not source and path_edit.text() != text:
                    path_edit.setText(text)
            self.settings.save_path = text.strip()
        finally:
            self._syncing_save_path = False

    def _persist_shared_save_path(self) -> None:
        self.settings.save_path = self.path_edit.text().strip()
        self.store.save(self.settings)

    def _check_runtime(self) -> None:
        missing = [path.name for path in (yt_dlp_path(), ffmpeg_path(), ffprobe_path(), deno_path()) if not path.exists()]
        if missing:
            self._append_log(f"运行时尚未完整：缺少 {', '.join(missing)}")
            self.statusBar().showMessage("缺少运行时文件")

    def _detect_hardware(self) -> None:
        if not ffmpeg_path().exists():
            return
        self.statusBar().showMessage("正在检测硬件加速能力...")
        QApplication.processEvents()
        self.hardware_availability = FFmpegService().detect_encoders(self._append_log)
        self.transcode_panel.set_available_hardware(self.hardware_availability)
        if self.first_run and self.hardware_availability.get("nvidia"):
            self.video_encoder_combo.setCurrentIndex(self.video_encoder_combo.findData("nvidia"))
        elif self.video_encoder_combo.currentData() != "cpu" and not self.hardware_availability.get(
            self.video_encoder_combo.currentData(), False
        ):
            self.video_encoder_combo.setCurrentIndex(self.video_encoder_combo.findData("cpu"))
        self.statusBar().showMessage("就绪")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            dialog.apply(self.settings)
            self.store.save(self.settings)
            self._append_log("设置已保存（代理密码未写入磁盘）")

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.path_edit.text())
        if path:
            self.path_edit.setText(path)
            self.path_edit.editingFinished.emit()

    def _select_subtitles(self) -> None:
        if not self.media:
            return
        dialog = SubtitleDialog(
            self.media.subtitle_options,
            self.subtitle_selections,
            self.settings.subtitle_format,
            self.settings.show_all_automatic_subtitles,
            self,
        )
        if dialog.exec():
            self.subtitle_selections = dialog.selections()
            self.settings.subtitle_format = dialog.subtitle_format()
            self.settings.show_all_automatic_subtitles = dialog.show_all_automatic()
            self._update_subtitle_summary()

    def _update_subtitle_summary(self) -> None:
        if not self.media:
            self.subtitle_summary.setText("请先分析视频")
            return
        if not self.media.subtitle_options:
            self.subtitle_summary.setText("该视频没有可用字幕")
            return
        if not self.subtitle_selections:
            self.subtitle_summary.setText(
                f"未选择（人工 {len(self.media.subtitles)}，自动 {len(self.media.automatic_captions)}）"
            )
            return
        labels = [
            f"{item.language}（{'人工' if item.kind == 'manual' else '自动'}）"
            for item in self.subtitle_selections
        ]
        self.subtitle_summary.setText(f"{', '.join(labels)} · {self.settings.subtitle_format.upper()}")

    def _open_output(self) -> None:
        path = self._last_output_dir
        if path is None or not path.is_dir():
            path = Path(self.path_edit.text()).expanduser()
            path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _request_from_ui(self) -> DownloadRequest:
        output = Path(self.path_edit.text().strip()).expanduser()
        if not self.url_edit.text().strip():
            raise ValueError("请先输入 YouTube、Instagram、TikTok 视频或 X 帖子网址")
        if not self.path_edit.text().strip():
            raise ValueError("请选择保存目录")
        template = self.filename_template.text().strip() or "{title} [{id}]"
        render_filename_template(
            template,
            {
                "title": self.media.title if self.media else "视频标题",
                "id": self.media.media_id if self.media else "ID",
                "channel": self.media.channel if self.media else "频道",
                "platform": self.media.platform if self.media else "YouTube",
                "upload_date": self.media.upload_date if self.media else "2026-01-01",
            },
        )
        transcode = self.transcode_panel.to_config(
            source_video_bitrate_kbps=self._source_video_bitrate_hint(),
            source_video_codec=self._source_video_codec_hint(),
        )
        video_id = self._selected_format_id(self.video_table)
        audio_id = self._selected_format_id(self.audio_table)
        return DownloadRequest(
            url=self.url_edit.text().strip(),
            output_dir=output,
            media_title=self.media.title if self.media else "",
            media_id=self.media.media_id if self.media else "",
            media_channel=self.media.channel if self.media else "",
            media_upload_date=self.media.upload_date if self.media else "",
            media_platform=self.media.platform if self.media else "YouTube",
            filename_template=template,
            classify_by_platform=self.classify_check.isChecked(),
            mode=self.mode_combo.currentData(),
            quality_preset=self.quality_combo.currentData(),
            custom_height=self.custom_height.value(),
            video_format_id=video_id,
            audio_format_id=audio_id,
            audio_output=self.audio_output.currentData(),
            proxy=self.settings.proxy,
            cookie_file=self.settings.cookie_file,
            cookie_browser=self.settings.cookie_browser,
            timeout=self.settings.timeout,
            download_thumbnail=self.download_thumbnail_check.isChecked() or self.mode_combo.currentData() == "cover",
            download_subtitles=bool(self.subtitle_selections) and self.mode_combo.currentData() != "cover",
            subtitle_selections=list(self.subtitle_selections),
            subtitle_format=self.settings.subtitle_format,
            transcode=transcode,
        )

    def _source_video_bitrate_hint(self) -> int | None:
        if not self.media:
            return None
        selected_id = self._selected_format_id(self.video_table)
        if self.mode_combo.currentData() == "advanced" and selected_id:
            selected = next((item for item in self.media.formats if item.format_id == selected_id), None)
            return round(selected.vbr or selected.tbr) if selected and (selected.vbr or selected.tbr) else None
        height = None
        preset = self.quality_combo.currentData()
        if preset == "custom":
            height = self.custom_height.value()
        elif isinstance(preset, str) and preset.endswith("p") and preset[:-1].isdigit():
            height = int(preset[:-1])
        candidates = [item for item in video_formats(self.media.formats) if not height or (item.height or 0) <= height]
        if not candidates:
            return None
        chosen = candidates[0] if preset != "worst" else candidates[-1]
        return round(chosen.vbr or chosen.tbr) if (chosen.vbr or chosen.tbr) else None

    def _source_video_codec_hint(self) -> str:
        if not self.media:
            return ""
        selected_id = self._selected_format_id(self.video_table)
        if self.mode_combo.currentData() == "advanced" and selected_id:
            selected = next((item for item in self.media.formats if item.format_id == selected_id), None)
            return selected.vcodec if selected else ""
        height = None
        preset = self.quality_combo.currentData()
        if preset == "custom":
            height = self.custom_height.value()
        elif isinstance(preset, str) and preset.endswith("p") and preset[:-1].isdigit():
            height = int(preset[:-1])
        candidates = [item for item in video_formats(self.media.formats) if not height or (item.height or 0) <= height]
        if not candidates:
            return ""
        chosen = candidates[0] if preset != "worst" else candidates[-1]
        return chosen.vcodec

    @staticmethod
    def _selected_format_id(table: QTableWidget) -> str | None:
        row = table.currentRow()
        return table.item(row, 0).text() if row >= 0 and table.item(row, 0) else None

    def _analyze(self) -> None:
        if self.thread:
            return
        platform = proxy_recommended_platform(self.url_edit.text())
        if platform and self.settings.proxy.scheme == "direct":
            answer = QMessageBox.question(
                self,
                "可能无法连接",
                f"检测到 {platform} 链接，但当前未设置代理。\n"
                "在中国大陆网络环境下可能无法连接或分析超时。\n\n"
                "是否仍要继续分析？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            request = self._request_from_ui()
        except ValueError as exc:
            QMessageBox.warning(self, "无法分析", str(exc))
            return
        self._analysis_running = True
        self.media = None
        self.thumbnail.clear()
        self.thumbnail.setText("正在分析")
        self._thumbnail_candidates = []
        self._thumbnail_generation += 1
        self.subtitle_selections = []
        self.subtitle_button.setEnabled(False)
        self._update_subtitle_summary()
        self.download_button.setEnabled(False)
        self._set_busy(True, "正在分析链接...")
        self._set_analysis_progress()
        worker = AnalyzeWorker(request)
        self._start_worker(worker, worker.run)
        worker.completed.connect(self._analysis_complete)
        worker.failed.connect(self._task_failed)

    def _download(self) -> None:
        if self.thread:
            return
        try:
            request = self._request_from_ui()
            if request.mode == "advanced" and not request.video_format_id:
                raise ValueError("高级流组合模式必须选择一个视频流")
        except ValueError as exc:
            QMessageBox.warning(self, "无法下载", str(exc))
            return
        self._analysis_running = False
        self._save_ui_settings()
        self._set_busy(True, "正在启动下载...")
        worker = DownloadWorker(request)
        self._start_worker(worker, worker.run)
        worker.progress.connect(self._update_progress)
        worker.completed.connect(self._download_complete)
        worker.gpu_fallback_requested.connect(self._ask_gpu_fallback)

    def _ask_gpu_fallback(self, diagnostic: str) -> None:
        answer = QMessageBox.question(
            self,
            "GPU 转码失败",
            f"{diagnostic}\n\n是否改用 CPU 继续转码？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if self.worker:
            self.worker.resolve_gpu_fallback(answer == QMessageBox.Yes)

    def _start_worker(self, worker, run_slot) -> None:
        thread = QThread(self)
        self.thread = thread
        self.worker = worker
        worker.moveToThread(thread)
        thread.started.connect(run_slot)
        self.cancel_requested.connect(worker.cancel, Qt.DirectConnection)
        worker.log.connect(self._append_log)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.start()

    def _cancel(self) -> None:
        if self.worker:
            self.cancel_button.setEnabled(False)
            self.stop_analysis_button.setEnabled(False)
            self.progress_label.setText("正在取消...")
            self.cancel_requested.emit()

    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None
        self._analysis_running = False
        self._set_busy(False, self.progress_label.text())

    def _analysis_complete(self, media: MediaInfo) -> None:
        self._reset_analysis_progress()
        self.media = media
        self.title_label.setText(media.title)
        duration = int(media.duration or 0)
        self.meta_label.setText(
            f"平台：{media.platform or '未知'}    频道：{media.channel or '未知'}    "
            f"时长：{duration // 60:02d}:{duration % 60:02d}    ID：{media.media_id}"
        )
        cookie_status = inspect_cookie_status(
            media.platform,
            self.settings.cookie_file,
            self.settings.cookie_browser,
        )
        self.cookie_status_label.setText(f"Cookie：{cookie_status.text}")
        color = {"valid": "#15803d", "invalid": "#dc2626", "warning": "#b45309"}.get(
            cookie_status.state, "#687386"
        )
        self.cookie_status_label.setStyleSheet(f"color:{color}")
        self._populate_table(self.video_table, video_formats(media.formats))
        self._populate_table(self.audio_table, audio_formats(media.formats), allow_none=True)
        videos = [item for item in media.formats if item.has_video]
        hint = max(videos, key=lambda item: ((item.width or 0) * (item.height or 0), item.vbr or 0), default=None)
        self.transcode_panel.set_media_hint(
            hint.width if hint else None,
            hint.height if hint else None,
            hint.fps if hint else None,
            media.duration,
        )
        self.subtitle_button.setEnabled(bool(media.subtitle_options) and self.mode_combo.currentData() != "cover")
        self._update_subtitle_summary()
        self.download_button.setEnabled(True)
        self.progress_label.setText(f"分析完成，共 {len(media.formats)} 个格式")
        self.total_progress.setValue(0)
        self.stage_progress.setRange(0, 100)
        self.stage_progress.setValue(0)
        self._update_filename_preview()
        self._thumbnail_candidates = media.thumbnail_candidates
        configure_preview_proxy(self.network, self.settings.proxy)
        self._load_next_thumbnail(self._thumbnail_generation)

    def _load_next_thumbnail(self, generation: int) -> None:
        if generation != self._thumbnail_generation:
            return
        if not self._thumbnail_candidates:
            if not self.thumbnail.pixmap() or self.thumbnail.pixmap().isNull():
                self.thumbnail.setText("暂无可用封面")
            return
        url = self._thumbnail_candidates.pop(0)
        reply = self.network.get(thumbnail_request(url, self.media.platform if self.media else ""))
        reply.finished.connect(lambda: self._thumbnail_ready(reply, generation))

    def _thumbnail_ready(self, reply: QNetworkReply, generation: int | None = None) -> None:
        generation = self._thumbnail_generation if generation is None else generation
        if generation != self._thumbnail_generation:
            reply.deleteLater()
            return
        data: QByteArray = reply.readAll()
        pixmap = QPixmap()
        if reply.error() == QNetworkReply.NoError and pixmap.loadFromData(data):
            self.thumbnail.setPixmap(pixmap.scaled(self.thumbnail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self._thumbnail_candidates = []
        else:
            self._load_next_thumbnail(generation)
        reply.deleteLater()

    @staticmethod
    def _populate_table(table: QTableWidget, formats: list[FormatInfo], allow_none: bool = False) -> None:
        table.setRowCount(0)
        for fmt in formats:
            row = table.rowCount()
            table.insertRow(row)
            values = (
                fmt.format_id,
                f"{fmt.width or '?'}×{fmt.height or '?'}" if fmt.has_video else "仅音频",
                f"{fmt.fps:g}" if fmt.fps else "",
                fmt.dynamic_range or "",
                fmt.vcodec if fmt.has_video else fmt.acodec,
                fmt.ext,
                f"{(fmt.vbr or fmt.abr or fmt.tbr):.0f}k" if (fmt.vbr or fmt.abr or fmt.tbr) else "未知",
                human_size(fmt.size),
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))
        if table.rowCount():
            table.selectRow(0)
        if allow_none:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(""))
            table.setItem(row, 1, QTableWidgetItem("不追加音频"))

    def _task_failed(self, category: str, message: str) -> None:
        self._reset_analysis_progress()
        if category == "已取消":
            self.progress_label.setText("分析已取消")
            self._append_log("分析已取消")
            return
        self.progress_label.setText(f"{category}：{message}")
        self._append_log(f"[{category}] {message}")
        QMessageBox.critical(self, f"分析失败：{category}", message)

    def _download_complete(self, result: TaskResult) -> None:
        if result.success:
            if result.output_directory is not None:
                self._last_output_dir = result.output_directory
            self.total_progress.setValue(100)
            self.stage_progress.setRange(0, 100)
            self.stage_progress.setValue(100)
            files = result.output_files or ([result.output_path] if result.output_path else [])
            self.progress_label.setText(f"完成：{files[0] if files else '任务完成'}")
            listing = "\n".join(str(path) for path in files)
            self._append_log(f"下载完成\n输出文件：\n{listing}")
        elif result.error_category == "已取消":
            self.progress_label.setText("任务已取消")
            self._append_log("任务已取消")
        else:
            self.progress_label.setText(f"{result.error_category}：{result.message}")
            self._append_log(f"[{result.error_category}] {result.message}")
            QMessageBox.critical(self, f"下载失败：{result.error_category}", result.message)

    def _update_progress(self, progress: TaskProgress) -> None:
        if progress.total_percent is not None:
            self.total_progress.setValue(max(0, min(100, int(progress.total_percent))))
        if progress.stage_indeterminate:
            self.stage_progress.setRange(0, 0)
            self.stage_progress.setFormat(f"{progress.stage}...")
        else:
            if self.stage_progress.maximum() == 0:
                self.stage_progress.setRange(0, 100)
            if progress.stage_percent is not None:
                self.stage_progress.setValue(max(0, min(100, int(progress.stage_percent))))
            self.stage_progress.setFormat(f"{progress.stage} %p%")
        details = "  ".join(
            value
            for value in (
                progress.current_item,
                progress.speed,
                progress.total,
                f"ETA {progress.eta}" if progress.eta and progress.eta != "NA" else "",
            )
            if value
        )
        self.progress_label.setText(f"{progress.stage} {details or progress.message}".strip())

    def _append_log(self, text: str) -> None:
        if text:
            self.log.appendPlainText(text)

    def _set_busy(self, busy: bool, text: str) -> None:
        self.analyze_button.setEnabled(not busy)
        self.download_button.setEnabled(not busy and self.media is not None)
        self.cancel_button.setEnabled(busy)
        self.stop_analysis_button.setVisible(busy and self._analysis_running)
        self.stop_analysis_button.setEnabled(busy and self._analysis_running)
        self.progress_label.setText(text)

    def _set_analysis_progress(self) -> None:
        self.total_progress.setRange(0, 0)
        self.total_progress.setFormat("正在分析...")
        self.stage_progress.setRange(0, 0)
        self.stage_progress.setFormat("等待网站响应...")

    def _reset_analysis_progress(self) -> None:
        self.total_progress.setRange(0, 100)
        self.total_progress.setValue(0)
        self.total_progress.setFormat("总任务 %p%")
        self.stage_progress.setRange(0, 100)
        self.stage_progress.setValue(0)
        self.stage_progress.setFormat("当前阶段 %p%")

    def _mode_changed(self) -> None:
        mode = self.mode_combo.currentData()
        cover_only = mode == "cover"
        self.mode_combo.setEnabled(True)
        self.quality_combo.setEnabled(mode in {"video_audio", "video_only"})
        self.custom_height.setEnabled(mode in {"video_audio", "video_only"})
        self.audio_output.setEnabled(mode == "audio")
        self.format_tabs.setEnabled(mode == "advanced")
        self.transcode_panel.setEnabled(not cover_only)
        self.transcode_panel.set_transcode_allowed(mode not in {"audio", "video_only", "cover"})
        self.download_thumbnail_check.setEnabled(not cover_only)
        self.subtitle_button.setEnabled(not cover_only and bool(self.media and self.media.subtitle_options))
        self.download_thumbnail_check.setText("仅封面模式自动下载" if cover_only else "下载封面")
        self._update_filename_preview()

    def _update_stream_selection(self) -> None:
        self.video_selection_label.setText(f"当前视频流：{self._selected_format_id(self.video_table) or '未选择'}")
        self.audio_selection_label.setText(f"当前音频流：{self._selected_format_id(self.audio_table) or '不追加音频'}")

    def _update_filename_preview(self) -> None:
        try:
            preview = render_filename_template(
                self.filename_template.text().strip() or "{title} [{id}]",
                {
                    "title": self.media.title if self.media else "视频标题",
                    "id": self.media.media_id if self.media else "ID",
                    "channel": self.media.channel if self.media else "频道",
                    "platform": self.media.platform if self.media else "YouTube",
                    "upload_date": self.media.upload_date if self.media else "20260101",
                },
            )
            extension = "原始图片格式" if self.mode_combo.currentData() == "cover" else "mp4"
            self.filename_preview.setText(f"预览：{preview}.{extension}")
            self.filename_preview.setStyleSheet("color:#475569")
        except ValueError as exc:
            self.filename_preview.setText(str(exc))
            self.filename_preview.setStyleSheet("color:#dc2626")

    def _save_ui_settings(self) -> None:
        self.settings.save_path = self.path_edit.text().strip()
        self.settings.classify_by_platform = self.classify_check.isChecked()
        self.settings.output_mode = self.mode_combo.currentData()
        self.settings.filename_template = self.filename_template.text().strip() or "{title} [{id}]"
        self.settings.download_thumbnail = self.download_thumbnail_check.isChecked()
        self.settings.download_subtitles = bool(self.subtitle_selections)
        self.settings.transcode = self.transcode_panel.to_config()
        self.store.save(self.settings)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread or self.douyin_page.is_busy() or self.xiaohongshu_page.is_busy() or self.bilibili_page.is_busy():
            answer = QMessageBox.question(self, "任务运行中", "任务仍在运行，确定要取消并退出吗？")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            if self.thread:
                self.cancel_requested.emit()
                self.thread.quit()
                self.thread.wait(3000)
            self.douyin_page.shutdown()
            self.xiaohongshu_page.shutdown()
            self.bilibili_page.shutdown()
        self._save_ui_settings()
        event.accept()
