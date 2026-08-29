from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .config import AppSettings, SettingsStore
from .cookie_status import inspect_cookie_status
from .models import TaskProgress, TaskResult, XiaohongshuDownloadRequest, XiaohongshuMediaInfo
from .naming_widgets import create_url_action_buttons, template_button_widget
from .thumbnail_preview import configure_preview_proxy, thumbnail_request
from .utils import render_filename_template
from .xiaohongshu import select_video_asset
from .xiaohongshu_workers import XiaohongshuAnalyzeWorker, XiaohongshuDownloadWorker


class XiaohongshuPage(QWidget):
    cancel_requested = Signal()

    def __init__(self, settings: AppSettings, store: SettingsStore, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.store = store
        self.media: XiaohongshuMediaInfo | None = None
        self.thread: QThread | None = None
        self.worker = None
        self._analysis_running = False
        self._last_output_dir: Path | None = None
        self.network = QNetworkAccessManager(self)
        self._build_ui()
        self._apply_settings()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self); root.setContentsMargins(8, 7, 8, 7); root.setSpacing(6)
        row = QGridLayout(); row.setHorizontalSpacing(6)
        self.url_edit = QLineEdit(); self.url_edit.setPlaceholderText("粘贴小红书单篇视频、图文、短链接或包含链接的分享文本")
        self.clear_url_button, self.paste_url_button = create_url_action_buttons(self.url_edit)
        self.analyze_button = QPushButton("分析笔记"); self.analyze_button.clicked.connect(self._analyze)
        self.stop_analysis_button = QPushButton("停止分析"); self.stop_analysis_button.setProperty("danger", True); self.stop_analysis_button.setVisible(False); self.stop_analysis_button.clicked.connect(self.cancel)
        row.addWidget(QLabel("网址"), 0, 0); row.addWidget(self.url_edit, 0, 1); row.addWidget(self.clear_url_button, 0, 2); row.addWidget(self.paste_url_button, 0, 3); row.addWidget(self.analyze_button, 0, 4); row.addWidget(self.stop_analysis_button, 0, 5); row.setColumnStretch(1, 1); root.addLayout(row)

        option_row = QHBoxLayout()
        self.video_preference = QComboBox()
        self.video_preference.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for label, value in (("最高分辨率", "resolution"), ("最高码率", "bitrate"), ("最小体积", "size")):
            self.video_preference.addItem(label, value)
        self.image_format = QComboBox()
        for label, value in (("原格式", "auto"), ("JPEG", "jpeg"), ("PNG", "png"), ("WEBP", "webp")):
            self.image_format.addItem(label, value)
        self.image_format.currentIndexChanged.connect(self._image_format_changed)
        option_row.addWidget(QLabel("下载版本")); option_row.addWidget(self.video_preference, 1); option_row.addWidget(QLabel("图片格式")); option_row.addWidget(self.image_format); root.addLayout(option_row)

        path_row = QGridLayout(); path_row.setHorizontalSpacing(6)
        self.path_edit = QLineEdit(); browse = QPushButton("选择..."); browse.clicked.connect(self._browse)
        self.classify_check = QCheckBox("按平台分类保存"); self.classify_author_check = QCheckBox("按作者分类保存")
        path_row.addWidget(QLabel("保存到"), 0, 0); path_row.addWidget(self.path_edit, 0, 1); path_row.addWidget(browse, 0, 2); path_row.addWidget(self.classify_check, 0, 3); path_row.addWidget(self.classify_author_check, 0, 4); path_row.setColumnStretch(1, 1); root.addLayout(path_row)

        info = QGroupBox("笔记信息"); info_layout = QHBoxLayout(info)
        self.thumbnail = QLabel("等待分析"); self.thumbnail.setFixedSize(164, 164); self.thumbnail.setAlignment(Qt.AlignCenter); self.thumbnail.setStyleSheet("background:#20242b;border-radius:6px;color:#9aa4b2")
        details = QVBoxLayout(); self.title_label = QLabel("尚未分析笔记"); self.title_label.setWordWrap(True); self.meta_label = QLabel(); self.meta_label.setWordWrap(True); self.cookie_status_label = QLabel("Cookie：等待分析"); self.cookie_status_label.setWordWrap(True)
        note = QLabel("自研内核直接解析小红书笔记网页；不调用 yt-dlp，也不执行转码。"); note.setWordWrap(True); note.setStyleSheet("color:#687386")
        details.addWidget(self.title_label); details.addWidget(self.meta_label); details.addWidget(self.cookie_status_label); details.addWidget(note); details.addStretch(); info_layout.addWidget(self.thumbnail); info_layout.addLayout(details, 1); root.addWidget(info)

        options = QGroupBox("下载选项（自研引擎，无转码）"); grid = QGridLayout(options); grid.setHorizontalSpacing(6); grid.setVerticalSpacing(4)
        self.filename_template = QLineEdit("{title} [{id}]"); self.filename_template.textChanged.connect(self._preview)
        self.cover_check = QCheckBox("视频同时下载封面")
        self.preview_label = QLabel("预览：等待分析"); self.preview_label.setWordWrap(True)
        grid.addWidget(QLabel("命名模板"), 0, 0); grid.addWidget(self.filename_template, 0, 1, 1, 7)
        fields = template_button_widget(self.filename_template, (("标题", "{title}"), ("ID", "{id}"), ("作者", "{author}"), ("平台", "{platform}"), ("发布日期", "{upload_date}"), ("下载日期", "{download_date}"), ("类型", "{type}")))
        grid.addWidget(fields, 1, 1, 1, 7); grid.addWidget(self.cover_check, 2, 1, 1, 7); grid.addWidget(QLabel("输出"), 3, 0); grid.addWidget(self.preview_label, 3, 1, 1, 7); grid.setColumnStretch(1, 1); root.addWidget(options)

        controls = QGridLayout(); controls.setHorizontalSpacing(6)
        self.download_button = QPushButton("开始下载"); self.download_button.setEnabled(False); self.download_button.clicked.connect(self._download)
        self.cancel_button = QPushButton("取消"); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(self.cancel)
        self.open_folder_button = QPushButton("打开保存目录"); self.open_folder_button.setProperty("secondary", True); self.open_folder_button.clicked.connect(self._open_output)
        self.total_progress = QProgressBar(); self.total_progress.setFormat("总任务 %p%")
        self.stage_progress = QProgressBar(); self.stage_progress.setFormat("当前阶段 %p%")
        controls.addWidget(self.download_button, 0, 0); controls.addWidget(self.cancel_button, 0, 1); controls.addWidget(self.open_folder_button, 0, 2); controls.addWidget(self.total_progress, 0, 3); controls.addWidget(self.stage_progress, 0, 4); controls.setColumnStretch(3, 1); controls.setColumnStretch(4, 1); root.addLayout(controls)
        self.progress_label = QLabel("就绪"); root.addWidget(self.progress_label)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000); self.log.setPlaceholderText("小红书分析、图片、实况和视频下载日志会显示在这里"); root.addWidget(self.log, 1)

    def _apply_settings(self) -> None:
        self.path_edit.setText(str(self.settings.resolved_save_path)); self.classify_check.setChecked(self.settings.classify_by_platform); self.classify_author_check.setChecked(self.settings.xiaohongshu_classify_by_author)
        self.filename_template.setText(self.settings.filename_template); self.cover_check.setChecked(self.settings.download_thumbnail)
        self.video_preference.setCurrentIndex(max(0, self.video_preference.findData(self.settings.xiaohongshu_video_preference)))
        self.image_format.setCurrentIndex(max(0, self.image_format.findData(self.settings.xiaohongshu_image_format)))

    def _reset_video_versions(self) -> None:
        self.video_preference.clear()
        for label, value in (("自动：最高分辨率", "resolution"), ("自动：最高码率", "bitrate"), ("自动：最小体积", "size")):
            self.video_preference.addItem(label, value)
        index = self.video_preference.findData(self.settings.xiaohongshu_video_preference)
        self.video_preference.setCurrentIndex(index if index >= 0 else 0)
        self.video_preference.setEnabled(True)

    def _refresh_video_versions(self, media: XiaohongshuMediaInfo) -> None:
        if media.media_type != "video":
            self.video_preference.clear()
            self.video_preference.addItem("图文笔记（无视频版本）", None)
            self.video_preference.setEnabled(False)
            return
        preference = self.settings.xiaohongshu_video_preference
        compatible = [
            (index, asset)
            for index, asset in enumerate(media.video_assets)
            if not asset.codec.upper().startswith("EF") or asset.codec.upper() == "EF4"
        ]
        compatible.sort(
            key=lambda pair: (
                pair[1].codec != "original",
                -((pair[1].width or 0) * (pair[1].height or 0)),
                -(pair[1].bitrate or 0),
                -(pair[1].size or 0),
            )
        )
        self.video_preference.clear()
        for display_index, (asset_index, asset) in enumerate(compatible, start=1):
            details = []
            if asset.width and asset.height:
                details.append(f"{asset.width}×{asset.height}")
            if asset.bitrate:
                divisor = 1_000_000 if asset.bitrate >= 100_000 else 1_000
                details.append(f"{asset.bitrate / divisor:.2f} Mbps")
            codec = {"original": "原始视频", "h264": "H.264", "h265": "H.265", "hevc": "H.265", "ef4": "H.264"}.get(asset.codec.lower(), asset.codec or "未知编码")
            details.append(codec)
            if asset.size:
                details.append(f"{asset.size / 1024 / 1024:.1f} MB")
            label = f"版本 {display_index}：" + " · ".join(details)
            self.video_preference.addItem(label, f"asset:{asset_index}")
            self.video_preference.setItemData(self.video_preference.count() - 1, label, Qt.ToolTipRole)
        self.video_preference.setEnabled(bool(compatible))
        if compatible:
            try:
                preferred = select_video_asset(media.video_assets, preference)
                preferred_index = next(index for index, asset in compatible if asset == preferred)
            except (ValueError, StopIteration):
                preferred_index = compatible[0][0]
            selected = self.video_preference.findData(f"asset:{preferred_index}")
            self.video_preference.setCurrentIndex(selected if selected >= 0 else 0)

    def _values(self) -> dict[str, str]:
        return {"title": self.media.title if self.media else "小红书笔记", "id": self.media.note_id if self.media else "ID", "author": self.media.author if self.media else "作者", "channel": self.media.author if self.media else "作者", "platform": "小红书", "upload_date": self.media.upload_date if self.media else "", "type": "视频" if not self.media or self.media.media_type == "video" else "图文"}

    def _request(self) -> XiaohongshuDownloadRequest:
        if not self.url_edit.text().strip(): raise ValueError("请先粘贴小红书笔记链接或分享文本")
        if not self.path_edit.text().strip(): raise ValueError("请选择保存目录")
        template = self.filename_template.text().strip() or "{title} [{id}]"; render_filename_template(template, self._values())
        cookie_file = self.settings.xiaohongshu_cookie_file or self.settings.cookie_file
        return XiaohongshuDownloadRequest(self.url_edit.text().strip(), Path(self.path_edit.text().strip()).expanduser(), self.video_preference.currentData(), self.image_format.currentData(), template, self.classify_check.isChecked(), self.classify_author_check.isChecked(), cookie_file, self.settings.proxy, self.settings.timeout, self.cover_check.isChecked(), self.media)

    def _analyze(self) -> None:
        if self.thread: return
        try: request = self._request()
        except ValueError as exc: QMessageBox.warning(self, "无法分析", str(exc)); return
        self.media = None; self._reset_video_versions(); self._analysis_running = True; self._set_busy(True, "正在分析小红书笔记..."); self.total_progress.setRange(0, 0); self.stage_progress.setRange(0, 0)
        if not self.settings.xiaohongshu_cookie_file and self.settings.cookie_file: self.log.appendPlainText("小红书专用 Cookie 未设置，正在使用 YouTube / Instagram / TikTok / X 通用 cookies.txt")
        worker = XiaohongshuAnalyzeWorker(request); self._start(worker, worker.run); worker.completed.connect(self._analysis_complete); worker.failed.connect(self._failed)

    def _download(self) -> None:
        if self.thread: return
        try: request = self._request()
        except ValueError as exc: QMessageBox.warning(self, "无法下载", str(exc)); return
        self._analysis_running = False; self._save_settings(); self._set_busy(True, "正在启动小红书下载...")
        worker = XiaohongshuDownloadWorker(request); self._start(worker, worker.run); worker.progress.connect(self._progress); worker.completed.connect(self._complete)

    def _start(self, worker, entry) -> None:
        thread = QThread(self); self.thread = thread; self.worker = worker; worker.moveToThread(thread); thread.started.connect(entry); self.cancel_requested.connect(worker.cancel, Qt.DirectConnection); worker.log.connect(self.log.appendPlainText); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater); thread.finished.connect(self._thread_finished); thread.start()

    def _analysis_complete(self, media: XiaohongshuMediaInfo) -> None:
        self.media = media; self.title_label.setText(media.title)
        self._refresh_video_versions(media)
        if media.media_type == "video": detail = f"视频资源：{len(media.video_assets)} 个"
        else: detail = f"静态图片：{len(media.image_assets)} 张    实况片段：{len(media.live_assets)} 个"
        self.meta_label.setText(f"类型：{'视频' if media.media_type == 'video' else '图文'}    作者：{media.author or '未知'}    ID：{media.note_id}\n{detail}")
        cookie_status = inspect_cookie_status("Xiaohongshu", self.settings.xiaohongshu_cookie_file or self.settings.cookie_file)
        self.cookie_status_label.setText(f"Cookie：{cookie_status.text}"); self.cookie_status_label.setStyleSheet(f"color:{ {'valid':'#15803d','invalid':'#dc2626','warning':'#b45309'}.get(cookie_status.state, '#687386') }")
        self.cover_check.setEnabled(media.media_type == "video"); self._reset_progress(); self._set_busy(False, "分析完成"); self._preview()
        if media.thumbnail:
            configure_preview_proxy(self.network, self.settings.proxy); reply = self.network.get(thumbnail_request(media.thumbnail, "Xiaohongshu")); reply.finished.connect(lambda: self._thumbnail_ready(reply))

    def _thumbnail_ready(self, reply: QNetworkReply) -> None:
        data: QByteArray = reply.readAll(); pixmap = QPixmap()
        if pixmap.loadFromData(data): self.thumbnail.setPixmap(pixmap.scaled(self.thumbnail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        reply.deleteLater()

    def _failed(self, category: str, message: str) -> None:
        self.media = None; self._reset_video_versions(); self._reset_progress(); self._set_busy(False, "分析已取消" if category == "已取消" else message); self.log.appendPlainText(f"[{category}] {message}")
        if category != "已取消": QMessageBox.critical(self, f"小红书分析失败：{category}", message)

    def _complete(self, result: TaskResult) -> None:
        self._reset_progress(); self._set_busy(False, result.message)
        if result.success:
            if result.output_directory is not None: self._last_output_dir = result.output_directory
            self.log.appendPlainText("下载完成\n输出文件：\n" + "\n".join(str(path) for path in result.output_files))
        elif result.error_category != "已取消": QMessageBox.critical(self, f"小红书下载失败：{result.error_category}", result.message)

    def _progress(self, item: TaskProgress) -> None:
        if item.total_percent is not None: self.total_progress.setRange(0, 100); self.total_progress.setValue(round(item.total_percent))
        if item.stage_indeterminate or item.stage_percent is None: self.stage_progress.setRange(0, 0)
        else: self.stage_progress.setRange(0, 100); self.stage_progress.setValue(round(item.stage_percent))
        self.progress_label.setText(f"{item.stage} {item.current_item or item.message}".strip())

    def _preview(self) -> None:
        try:
            stem = render_filename_template(self.filename_template.text().strip() or "{title} [{id}]", self._values())
            self.preview_label.setText(f"{stem}.mp4" if not self.media or self.media.media_type == "video" else f"{stem}\\01.{self.image_format.currentData() if self.image_format.currentData() != 'auto' else '原格式'}")
        except ValueError as exc: self.preview_label.setText(f"模板错误：{exc}")

    def _image_format_changed(self) -> None:
        self._preview()
        if self.media and self.media.media_type == "gallery": self.media = None; self.download_button.setEnabled(False); self.progress_label.setText("图片格式已更改，请重新分析")

    def _save_settings(self) -> None:
        self.settings.save_path = self.path_edit.text().strip(); self.settings.classify_by_platform = self.classify_check.isChecked(); self.settings.xiaohongshu_classify_by_author = self.classify_author_check.isChecked()
        if self.video_preference.currentData() in {"resolution", "bitrate", "size"}: self.settings.xiaohongshu_video_preference = self.video_preference.currentData()
        self.settings.xiaohongshu_image_format = self.image_format.currentData(); self.settings.filename_template = self.filename_template.text().strip() or "{title} [{id}]"; self.settings.download_thumbnail = self.cover_check.isChecked(); self.store.save(self.settings)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.path_edit.text())
        if path: self.path_edit.setText(path); self.path_edit.editingFinished.emit()

    def _open_output(self) -> None:
        path = self._last_output_dir
        if path is None or not path.is_dir():
            path = Path(self.path_edit.text().strip()).expanduser(); path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _reset_progress(self) -> None:
        self.total_progress.setRange(0, 100); self.total_progress.setValue(0); self.stage_progress.setRange(0, 100); self.stage_progress.setValue(0)

    def _set_busy(self, busy: bool, text: str) -> None:
        self.analyze_button.setEnabled(not busy); self.download_button.setEnabled(not busy and self.media is not None); self.cancel_button.setEnabled(busy); self.stop_analysis_button.setVisible(busy and self._analysis_running); self.progress_label.setText(text)

    def _thread_finished(self) -> None:
        self.thread = None; self.worker = None; self._analysis_running = False; self._set_busy(False, self.progress_label.text())

    def cancel(self) -> None:
        if self.worker: self.cancel_button.setEnabled(False); self.stop_analysis_button.setEnabled(False); self.progress_label.setText("正在取消..."); self.cancel_requested.emit()

    def is_busy(self) -> bool: return self.thread is not None

    def shutdown(self) -> None:
        if self.thread: self.cancel_requested.emit(); self.thread.quit(); self.thread.wait(3000)
