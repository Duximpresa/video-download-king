from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QPixmap
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
from .formats import audio_formats, video_formats
from .models import DownloadRequest, FormatInfo, MediaInfo, ProxyConfig, TaskProgress, TaskResult, TranscodeConfig
from .paths import deno_path, ffmpeg_path, ffprobe_path, yt_dlp_path
from .settings_dialog import SettingsDialog
from .utils import human_size
from .workers import AnalyzeWorker, DownloadWorker


class MainWindow(QMainWindow):
    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.store = SettingsStore()
        self.settings = self.store.load()
        self.media: MediaInfo | None = None
        self.thread: QThread | None = None
        self.worker = None
        self.network = QNetworkAccessManager(self)

        self.setWindowTitle("Video Download King 0.1.0")
        self.resize(1180, 820)
        self._build_menu()
        self._build_ui()
        self._apply_settings()
        self._check_runtime()

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("设置")
        action = QAction("网络与 YouTube 登录...", self)
        action.triggered.connect(self._open_settings)
        menu.addAction(action)
        help_menu = self.menuBar().addMenu("帮助")
        about = QAction("关于", self)
        about.triggered.connect(
            lambda: QMessageBox.information(
                self,
                "关于",
                "Video Download King 0.1.0\n基于 yt-dlp 与 FFmpeg。",
            )
        )
        help_menu.addAction(about)

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._build_single_tab(), "单链接下载")
        tabs.addTab(self._build_batch_tab(), "批量下载")
        self.setCentralWidget(tabs)
        self.statusBar().showMessage("就绪")

    def _build_single_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)

        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("粘贴 YouTube 单视频链接")
        self.analyze_button = QPushButton("分析链接")
        self.analyze_button.clicked.connect(self._analyze)
        url_row.addWidget(QLabel("网址"))
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.analyze_button)
        root.addLayout(url_row)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        browse = QPushButton("选择...")
        browse.clicked.connect(self._browse_output)
        self.classify_check = QCheckBox("按平台分类保存")
        path_row.addWidget(QLabel("保存到"))
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        path_row.addWidget(self.classify_check)
        root.addLayout(path_row)

        info_group = QGroupBox("视频信息")
        info_layout = QHBoxLayout(info_group)
        self.thumbnail = QLabel("等待分析")
        self.thumbnail.setFixedSize(240, 135)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self.thumbnail.setStyleSheet("background:#20242b;border-radius:6px;color:#9aa4b2")
        self.title_label = QLabel("尚未分析链接")
        self.title_label.setWordWrap(True)
        self.meta_label = QLabel("")
        details = QVBoxLayout()
        details.addWidget(self.title_label)
        details.addWidget(self.meta_label)
        details.addStretch()
        info_layout.addWidget(self.thumbnail)
        info_layout.addLayout(details, 1)
        root.addWidget(info_group)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_format_panel())
        splitter.addWidget(self._build_transcode_panel())
        splitter.setSizes([700, 430])
        root.addWidget(splitter, 1)
        self._mode_changed()

        controls = QHBoxLayout()
        self.download_button = QPushButton("开始下载")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._download)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        self.open_folder_button = QPushButton("打开保存目录")
        self.open_folder_button.clicked.connect(self._open_output)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        controls.addWidget(self.download_button)
        controls.addWidget(self.cancel_button)
        controls.addWidget(self.open_folder_button)
        controls.addWidget(self.progress, 1)
        root.addLayout(controls)

        self.progress_label = QLabel("就绪")
        root.addWidget(self.progress_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText("分析、下载和转码日志会显示在这里")
        root.addWidget(self.log, 1)
        return page

    def _build_format_panel(self) -> QWidget:
        group = QGroupBox("输出与格式")
        layout = QVBoxLayout(group)
        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("视频", "video")
        self.mode_combo.addItem("仅音频", "audio")
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
        self.video_table = self._new_format_table()
        self.audio_table = self._new_format_table()
        self.format_tabs.addTab(self.video_table, "视频流")
        self.format_tabs.addTab(self.audio_table, "音频流")
        layout.addWidget(self.format_tabs, 1)
        return group

    @staticmethod
    def _new_format_table() -> QTableWidget:
        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels(["ID", "分辨率", "FPS", "HDR", "编码", "容器", "码率", "大小"])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _build_transcode_panel(self) -> QWidget:
        group = QGroupBox("兼容 MP4")
        layout = QVBoxLayout(group)
        self.transcode_check = QCheckBox("自动生成 H.264 + AAC 的 MP4")
        self.keep_source_check = QCheckBox("成功后保留原始下载文件")
        layout.addWidget(self.transcode_check)
        layout.addWidget(self.keep_source_check)
        form = QFormLayout()
        self.rate_mode = QComboBox()
        self.rate_mode.addItem("自动", "auto")
        self.rate_mode.addItem("恒定质量", "quality")
        self.rate_mode.addItem("目标码率", "bitrate")
        self.rate_mode.currentIndexChanged.connect(self._rate_mode_changed)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(0, 51)
        self.quality_spin.setValue(23)
        self.video_bitrate = QSpinBox()
        self.video_bitrate.setRange(0, 100000)
        self.video_bitrate.setSpecialValueText("自动")
        self.video_bitrate.setSuffix(" kbps")
        self.audio_bitrate = QComboBox()
        self.audio_bitrate.addItem("自动", 0)
        for value in (96, 128, 192, 256, 320):
            self.audio_bitrate.addItem(f"{value} kbps", value)
        self.audio_custom = QSpinBox()
        self.audio_custom.setRange(0, 512)
        self.audio_custom.setSpecialValueText("使用上方选项")
        self.audio_custom.setSuffix(" kbps")
        form.addRow("视频控制", self.rate_mode)
        form.addRow("质量值 (0-51)", self.quality_spin)
        form.addRow("视频码率", self.video_bitrate)
        form.addRow("音频码率", self.audio_bitrate)
        form.addRow("自定义音频码率", self.audio_custom)
        layout.addLayout(form)
        note = QLabel("自动检测 NVIDIA NVENC、Intel QSV、AMD AMF；不可用或失败时回退 CPU。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#687386")
        layout.addWidget(note)
        layout.addStretch()
        self._rate_mode_changed()
        return group

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
        tc = self.settings.transcode
        self.transcode_check.setChecked(tc.enabled)
        self.keep_source_check.setChecked(tc.keep_source)
        self.rate_mode.setCurrentIndex(max(0, self.rate_mode.findData(tc.rate_mode)))
        self.quality_spin.setValue(tc.quality)
        self.video_bitrate.setValue(tc.video_bitrate_kbps or 0)
        self.audio_bitrate.setCurrentIndex(max(0, self.audio_bitrate.findData(tc.audio_bitrate_kbps or 0)))

    def _check_runtime(self) -> None:
        missing = [path.name for path in (yt_dlp_path(), ffmpeg_path(), ffprobe_path(), deno_path()) if not path.exists()]
        if missing:
            self._append_log(f"运行时尚未完整：缺少 {', '.join(missing)}")
            self.statusBar().showMessage("缺少运行时文件")

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

    def _open_output(self) -> None:
        path = Path(self.path_edit.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _request_from_ui(self) -> DownloadRequest:
        output = Path(self.path_edit.text().strip()).expanduser()
        if not self.url_edit.text().strip():
            raise ValueError("请先输入 YouTube 视频网址")
        if not self.path_edit.text().strip():
            raise ValueError("请选择保存目录")
        audio_rate = self.audio_custom.value() or self.audio_bitrate.currentData() or None
        transcode = TranscodeConfig(
            enabled=self.transcode_check.isChecked(),
            keep_source=self.keep_source_check.isChecked(),
            rate_mode=self.rate_mode.currentData(),
            quality=self.quality_spin.value(),
            video_bitrate_kbps=self.video_bitrate.value() or None,
            audio_bitrate_kbps=audio_rate,
        )
        video_id = self._selected_format_id(self.video_table)
        audio_id = self._selected_format_id(self.audio_table)
        return DownloadRequest(
            url=self.url_edit.text().strip(),
            output_dir=output,
            media_title=self.media.title if self.media else "",
            media_id=self.media.media_id if self.media else "",
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
            transcode=transcode,
        )

    @staticmethod
    def _selected_format_id(table: QTableWidget) -> str | None:
        row = table.currentRow()
        return table.item(row, 0).text() if row >= 0 and table.item(row, 0) else None

    def _analyze(self) -> None:
        if self.thread:
            return
        try:
            request = self._request_from_ui()
        except ValueError as exc:
            QMessageBox.warning(self, "无法分析", str(exc))
            return
        self.media = None
        self.download_button.setEnabled(False)
        self._set_busy(True, "正在分析链接...")
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
        self._save_ui_settings()
        self._set_busy(True, "正在启动下载...")
        worker = DownloadWorker(request)
        self._start_worker(worker, worker.run)
        worker.progress.connect(self._update_progress)
        worker.completed.connect(self._download_complete)

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
            self.progress_label.setText("正在取消...")
            self.cancel_requested.emit()

    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None
        self._set_busy(False, self.progress_label.text())

    def _analysis_complete(self, media: MediaInfo) -> None:
        self.media = media
        self.title_label.setText(media.title)
        duration = int(media.duration or 0)
        self.meta_label.setText(
            f"平台：YouTube    时长：{duration // 60:02d}:{duration % 60:02d}    ID：{media.media_id}"
        )
        self._populate_table(self.video_table, video_formats(media.formats))
        self._populate_table(self.audio_table, audio_formats(media.formats), allow_none=True)
        self.download_button.setEnabled(True)
        self.progress_label.setText(f"分析完成，共 {len(media.formats)} 个格式")
        self.progress.setValue(0)
        if media.thumbnail:
            reply = self.network.get(QNetworkRequest(QUrl(media.thumbnail)))
            reply.finished.connect(lambda: self._thumbnail_ready(reply))

    def _thumbnail_ready(self, reply: QNetworkReply) -> None:
        data: QByteArray = reply.readAll()
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.thumbnail.setPixmap(pixmap.scaled(self.thumbnail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
        self.progress_label.setText(f"{category}：{message}")
        self._append_log(f"[{category}] {message}")
        QMessageBox.critical(self, f"分析失败：{category}", message)

    def _download_complete(self, result: TaskResult) -> None:
        if result.success:
            self.progress.setValue(100)
            self.progress_label.setText(f"完成：{result.output_path}")
            self._append_log(f"输出文件：{result.output_path}")
            QMessageBox.information(self, "任务完成", f"文件已保存：\n{result.output_path}")
        elif result.error_category == "已取消":
            self.progress_label.setText("任务已取消")
            self._append_log("任务已取消")
        else:
            self.progress_label.setText(f"{result.error_category}：{result.message}")
            self._append_log(f"[{result.error_category}] {result.message}")
            QMessageBox.critical(self, f"下载失败：{result.error_category}", result.message)

    def _update_progress(self, progress: TaskProgress) -> None:
        if progress.percent is not None:
            self.progress.setValue(max(0, min(100, int(progress.percent))))
        details = "  ".join(value for value in (progress.speed, progress.total, f"ETA {progress.eta}" if progress.eta else "") if value)
        self.progress_label.setText(f"{progress.stage} {details or progress.message}".strip())

    def _append_log(self, text: str) -> None:
        if text:
            self.log.appendPlainText(text)

    def _set_busy(self, busy: bool, text: str) -> None:
        self.analyze_button.setEnabled(not busy)
        self.download_button.setEnabled(not busy and self.media is not None)
        self.cancel_button.setEnabled(busy)
        self.progress_label.setText(text)

    def _mode_changed(self) -> None:
        mode = self.mode_combo.currentData()
        self.quality_combo.setEnabled(mode == "video")
        self.custom_height.setEnabled(mode == "video")
        self.audio_output.setEnabled(mode == "audio")
        self.format_tabs.setEnabled(mode == "advanced")
        self.transcode_check.setEnabled(mode != "audio")

    def _rate_mode_changed(self) -> None:
        mode = self.rate_mode.currentData()
        self.quality_spin.setEnabled(mode == "quality")
        self.video_bitrate.setEnabled(mode == "bitrate")

    def _save_ui_settings(self) -> None:
        self.settings.save_path = self.path_edit.text().strip()
        self.settings.classify_by_platform = self.classify_check.isChecked()
        audio_rate = self.audio_custom.value() or self.audio_bitrate.currentData() or None
        self.settings.transcode = TranscodeConfig(
            enabled=self.transcode_check.isChecked(),
            keep_source=self.keep_source_check.isChecked(),
            rate_mode=self.rate_mode.currentData(),
            quality=self.quality_spin.value(),
            video_bitrate_kbps=self.video_bitrate.value() or None,
            audio_bitrate_kbps=audio_rate,
        )
        self.store.save(self.settings)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread:
            answer = QMessageBox.question(self, "任务运行中", "任务仍在运行，确定要取消并退出吗？")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.cancel_requested.emit()
            self.thread.quit()
            self.thread.wait(3000)
        self._save_ui_settings()
        event.accept()
