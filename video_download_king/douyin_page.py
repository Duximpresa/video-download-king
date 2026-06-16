from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import AppSettings, SettingsStore
from .douyin_workers import DouyinAnalyzeWorker, DouyinDownloadWorker
from .models import DouyinDownloadRequest, DouyinMediaInfo, TaskProgress, TaskResult
from .transcode_panel import TranscodePanel
from .utils import render_filename_template


class DouyinPage(QWidget):
    cancel_requested = Signal()

    def __init__(self, settings: AppSettings, store: SettingsStore, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.store = store
        self.media: DouyinMediaInfo | None = None
        self.thread: QThread | None = None
        self.worker = None
        self.network = QNetworkAccessManager(self)
        self._build_ui()
        self._apply_settings()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("粘贴抖音单视频、图集链接或包含链接的分享文本")
        self.analyze_button = QPushButton("分析作品")
        self.analyze_button.clicked.connect(self._analyze)
        url_row.addWidget(QLabel("网址"))
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.analyze_button)
        root.addLayout(url_row)

        option_row = QHBoxLayout()
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("自研引擎（推荐，无水印/图集）", "native")
        self.engine_combo.addItem("yt-dlp", "yt_dlp")
        self.engine_combo.currentIndexChanged.connect(self._engine_changed)
        self.quality_combo = QComboBox()
        for label, value in (
            ("最高画质", "highest"),
            ("1080p", "1080p"),
            ("720p", "720p"),
            ("540p", "540p"),
            ("最低画质", "lowest"),
        ):
            self.quality_combo.addItem(label, value)
        option_row.addWidget(QLabel("下载引擎"))
        option_row.addWidget(self.engine_combo)
        option_row.addWidget(QLabel("画质"))
        option_row.addWidget(self.quality_combo)
        option_row.addStretch()
        root.addLayout(option_row)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        browse = QPushButton("选择...")
        browse.clicked.connect(self._browse_output)
        self.classify_check = QCheckBox("按平台分类保存")
        self.classify_author_check = QCheckBox("按作者分类保存")
        path_row.addWidget(QLabel("保存到"))
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        path_row.addWidget(self.classify_check)
        path_row.addWidget(self.classify_author_check)
        root.addLayout(path_row)

        info_group = QGroupBox("作品信息")
        info_layout = QHBoxLayout(info_group)
        self.thumbnail = QLabel("等待分析")
        self.thumbnail.setFixedSize(200, 200)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self.thumbnail.setStyleSheet("background:#20242b;border-radius:6px;color:#9aa4b2")
        details = QVBoxLayout()
        self.title_label = QLabel("尚未分析作品")
        self.title_label.setWordWrap(True)
        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        self.engine_note = QLabel("自研引擎直接解析抖音接口；yt-dlp 仅用于视频，不支持图集。")
        self.engine_note.setWordWrap(True)
        self.engine_note.setStyleSheet("color:#687386")
        details.addWidget(self.title_label)
        details.addWidget(self.meta_label)
        details.addWidget(self.engine_note)
        details.addStretch()
        info_layout.addWidget(self.thumbnail)
        info_layout.addLayout(details, 1)
        root.addWidget(info_group)

        download_group = QGroupBox("下载选项")
        download_form = QGridLayout(download_group)
        self.filename_template = QLineEdit("{title} [{id}]")
        self.filename_template.textChanged.connect(self._update_preview)
        self.download_thumbnail_check = QCheckBox("同时下载封面")
        self.preview_label = QLabel("预览：等待分析")
        self.preview_label.setWordWrap(True)
        download_form.addWidget(QLabel("命名模板"), 0, 0)
        download_form.addWidget(self.filename_template, 0, 1, 1, 7)
        fields = QHBoxLayout()
        for label, token in (
            ("标题", "{title}"),
            ("ID", "{id}"),
            ("作者", "{author}"),
            ("平台", "{platform}"),
            ("发布日期", "{upload_date}"),
            ("下载日期", "{download_date}"),
            ("类型", "{type}"),
            ("序号", "{index}"),
            ("资源", "{asset}"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=token: self.filename_template.insert(value))
            fields.addWidget(button)
        download_form.addLayout(fields, 1, 1, 1, 7)
        download_form.addWidget(self.download_thumbnail_check, 2, 1, 1, 7)
        download_form.addWidget(QLabel("文件名"), 3, 0)
        download_form.addWidget(self.preview_label, 3, 1, 1, 7)
        download_form.setColumnStretch(1, 1)
        root.addWidget(download_group)

        self.transcode_panel = TranscodePanel("兼容 MP4（仅视频）")
        self.transcode_group = self.transcode_panel
        root.addWidget(self.transcode_panel)

        controls = QHBoxLayout()
        self.download_button = QPushButton("开始下载")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._download)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        open_folder = QPushButton("打开保存目录")
        open_folder.clicked.connect(self._open_output)
        self.total_progress = QProgressBar()
        self.total_progress.setRange(0, 100)
        self.total_progress.setFormat("总任务 %p%")
        self.stage_progress = QProgressBar()
        self.stage_progress.setRange(0, 100)
        self.stage_progress.setFormat("当前阶段 %p%")
        controls.addWidget(self.download_button)
        controls.addWidget(self.cancel_button)
        controls.addWidget(open_folder)
        controls.addWidget(self.total_progress, 1)
        controls.addWidget(self.stage_progress, 1)
        root.addLayout(controls)

        self.progress_label = QLabel("就绪")
        root.addWidget(self.progress_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText("抖音分析、下载和转码日志会显示在这里")
        root.addWidget(self.log, 1)

    def _apply_settings(self) -> None:
        self.path_edit.setText(str(self.settings.resolved_save_path))
        self.classify_check.setChecked(self.settings.classify_by_platform)
        self.classify_author_check.setChecked(self.settings.douyin_classify_by_author)
        self.filename_template.setText(self.settings.filename_template)
        self.download_thumbnail_check.setChecked(self.settings.download_thumbnail)
        self.transcode_panel.load_config(self.settings.transcode)

    def _request(self) -> DouyinDownloadRequest:
        if not self.url_edit.text().strip():
            raise ValueError("请先粘贴抖音作品链接或分享文本")
        if not self.path_edit.text().strip():
            raise ValueError("请选择保存目录")
        template = self.filename_template.text().strip() or "{title} [{id}]"
        render_filename_template(template, self._template_values(index=1, asset="视频"))
        transcode_enabled = self.transcode_panel.transcode_check.isChecked() and bool(
            not self.media or self.media.media_type == "video"
        )
        return DouyinDownloadRequest(
            url=self.url_edit.text().strip(),
            output_dir=Path(self.path_edit.text().strip()).expanduser(),
            download_engine=self.engine_combo.currentData(),
            quality=self.quality_combo.currentData(),
            filename_template=template,
            classify_by_platform=self.classify_check.isChecked(),
            classify_by_author=self.classify_author_check.isChecked(),
            cookie_file=self.settings.douyin_cookie_file,
            proxy=self.settings.proxy,
            timeout=self.settings.timeout,
            download_thumbnail=self.download_thumbnail_check.isChecked(),
            transcode=self.transcode_panel.to_config(enabled=transcode_enabled),
            media=self.media,
        )

    def _analyze(self) -> None:
        if self.thread:
            return
        try:
            request = self._request()
        except ValueError as exc:
            QMessageBox.warning(self, "无法分析", str(exc))
            return
        self.media = None
        self.download_button.setEnabled(False)
        self._set_busy(True, "正在分析抖音作品...")
        worker = DouyinAnalyzeWorker(request)
        self._start_worker(worker, worker.run)
        worker.completed.connect(self._analysis_complete)
        worker.failed.connect(self._task_failed)
        worker.engine_fallback_requested.connect(self._ask_engine_fallback)

    def _download(self) -> None:
        if self.thread:
            return
        try:
            request = self._request()
        except ValueError as exc:
            QMessageBox.warning(self, "无法下载", str(exc))
            return
        self._save_settings()
        self._set_busy(True, "正在启动抖音下载...")
        worker = DouyinDownloadWorker(request)
        self._start_worker(worker, worker.run)
        worker.progress.connect(self._update_progress)
        worker.completed.connect(self._download_complete)
        worker.engine_fallback_requested.connect(self._ask_engine_fallback)
        worker.gpu_fallback_requested.connect(self._ask_gpu_fallback)

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

    def _analysis_complete(self, media: DouyinMediaInfo) -> None:
        self.media = media
        self.title_label.setText(media.title)
        if media.media_type == "gallery":
            image_count = sum(item.kind == "image" for item in media.gallery_assets)
            live_count = sum(item.kind == "live_photo" for item in media.gallery_assets)
            detail = f"图集：{image_count} 张图片"
            if live_count:
                detail += f"，{live_count} 个实况片段"
            self.engine_combo.setCurrentIndex(self.engine_combo.findData("native"))
            self.engine_combo.setEnabled(False)
            self.quality_combo.setEnabled(False)
            self.transcode_group.setEnabled(False)
        else:
            detail = f"视频：{len(media.video_assets) or '由 yt-dlp 提供'} 个可用格式"
            self.engine_combo.setEnabled(True)
            self.quality_combo.setEnabled(True)
            self.transcode_group.setEnabled(True)
        duration = int(media.duration or 0)
        self.meta_label.setText(
            f"类型：{'图集' if media.media_type == 'gallery' else '视频'}    "
            f"作者：{media.author or '未知'}    时长：{duration // 60:02d}:{duration % 60:02d}    "
            f"ID：{media.media_id}\n{detail}"
        )
        self.download_button.setEnabled(True)
        self.progress_label.setText("分析完成")
        self._update_preview()
        if media.thumbnail:
            reply = self.network.get(QNetworkRequest(QUrl(media.thumbnail)))
            reply.finished.connect(lambda: self._thumbnail_ready(reply))

    def _thumbnail_ready(self, reply: QNetworkReply) -> None:
        data: QByteArray = reply.readAll()
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.thumbnail.setPixmap(
                pixmap.scaled(self.thumbnail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        reply.deleteLater()

    def _ask_engine_fallback(self, target: str, diagnostic: str) -> None:
        label = "yt-dlp" if target == "yt_dlp" else "自研引擎"
        answer = QMessageBox.question(
            self,
            "下载引擎失败",
            f"{diagnostic}\n\n是否切换到 {label} 重新下载？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.engine_combo.setCurrentIndex(self.engine_combo.findData(target))
        if self.worker:
            self.worker.resolve_engine_fallback(answer == QMessageBox.Yes)

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

    def _task_failed(self, category: str, message: str) -> None:
        self.progress_label.setText(f"{category}：{message}")
        self._append_log(f"[{category}] {message}")
        QMessageBox.critical(self, f"抖音分析失败：{category}", message)

    def _download_complete(self, result: TaskResult) -> None:
        if result.success:
            self.total_progress.setValue(100)
            self.stage_progress.setRange(0, 100)
            self.stage_progress.setValue(100)
            listing = "\n".join(str(path) for path in result.output_files)
            self.progress_label.setText(f"完成：{result.output_files[0] if result.output_files else '任务完成'}")
            self._append_log(f"输出文件：\n{listing}")
            QMessageBox.information(self, "抖音任务完成", f"文件已保存：\n{listing}")
        elif result.error_category == "已取消":
            self.progress_label.setText("任务已取消")
            self._append_log("任务已取消")
        else:
            self.progress_label.setText(f"{result.error_category}：{result.message}")
            self._append_log(f"[{result.error_category}] {result.message}")
            QMessageBox.critical(self, f"抖音下载失败：{result.error_category}", result.message)

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
        self.progress_label.setText(
            f"{progress.stage} {progress.current_item or progress.message}".strip()
        )

    def _engine_changed(self) -> None:
        self.engine_note.setText(
            "自研引擎优先选择无水印高画质资源，并支持图集。"
            if self.engine_combo.currentData() == "native"
            else "yt-dlp 仅支持抖音视频；引擎失败时程序会询问是否切换。"
        )

    def _template_values(self, *, index: int | None = None, asset: str = "视频") -> dict[str, str]:
        media_type = "图集" if self.media and self.media.media_type == "gallery" else "视频"
        author = self.media.author if self.media else "作者"
        return {
            "title": self.media.title if self.media else "抖音作品",
            "id": self.media.media_id if self.media else "ID",
            "channel": author,
            "author": author,
            "platform": "Douyin",
            "upload_date": self.media.upload_date if self.media else "20260101",
            "type": media_type,
            "index": f"{index:02d}" if index is not None else "",
            "asset": asset,
        }

    def _update_preview(self) -> None:
        try:
            stem = render_filename_template(
                self.filename_template.text().strip() or "{title} [{id}]",
                self._template_values(index=1, asset="图片" if self.media and self.media.media_type == "gallery" else "视频"),
            )
            has_index_field = "{index}" in (self.filename_template.text().strip() or "{title} [{id}]")
            suffix = ("" if has_index_field else "_01") + ".jpg" if self.media and self.media.media_type == "gallery" else ".mp4"
            self.preview_label.setText(f"{stem}{suffix}")
            self.preview_label.setStyleSheet("color:#475569")
        except ValueError as exc:
            self.preview_label.setText(str(exc))
            self.preview_label.setStyleSheet("color:#dc2626")

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.path_edit.text())
        if path:
            self.path_edit.setText(path)

    def _open_output(self) -> None:
        path = Path(self.path_edit.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _save_settings(self) -> None:
        self.settings.save_path = self.path_edit.text().strip()
        self.settings.classify_by_platform = self.classify_check.isChecked()
        self.settings.douyin_classify_by_author = self.classify_author_check.isChecked()
        self.settings.filename_template = self.filename_template.text().strip() or "{title} [{id}]"
        self.settings.download_thumbnail = self.download_thumbnail_check.isChecked()
        self.settings.transcode = self.transcode_panel.to_config()
        self.store.save(self.settings)

    def _append_log(self, text: str) -> None:
        if text:
            self.log.appendPlainText(text)

    def _set_busy(self, busy: bool, text: str) -> None:
        self.analyze_button.setEnabled(not busy)
        self.download_button.setEnabled(not busy and self.media is not None)
        self.cancel_button.setEnabled(busy)
        self.progress_label.setText(text)

    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None
        self._set_busy(False, self.progress_label.text())

    def is_busy(self) -> bool:
        return self.thread is not None

    def cancel(self) -> None:
        if self.worker:
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("正在取消...")
            self.cancel_requested.emit()

    def shutdown(self) -> None:
        if self.thread:
            self.cancel_requested.emit()
            self.thread.quit()
            self.thread.wait(3000)
