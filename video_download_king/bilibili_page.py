from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView,QCheckBox,QComboBox,QFileDialog,QGridLayout,QGroupBox,QHBoxLayout,QHeaderView,QLabel,QLineEdit,QMessageBox,QPlainTextEdit,QProgressBar,QPushButton,QTableWidget,QTableWidgetItem,QTreeWidget,QTreeWidgetItem,QVBoxLayout,QWidget)

from .bilibili_workers import BilibiliAnalyzeWorker, BilibiliDownloadWorker
from .config import AppSettings, SettingsStore
from .models import BilibiliDownloadRequest,BilibiliMediaInfo,TaskProgress,TaskResult
from .naming_widgets import create_url_action_buttons, template_button_widget
from .utils import render_filename_template


class BilibiliPage(QWidget):
    cancel_requested=Signal()
    def __init__(self,settings:AppSettings,store:SettingsStore,parent=None)->None:
        super().__init__(parent); self.settings=settings; self.store=store; self.media:BilibiliMediaInfo|None=None; self.thread:QThread|None=None; self.worker=None; self._analysis_running=False; self._build_ui(); self._apply_settings()

    def _build_ui(self)->None:
        root=QVBoxLayout(self); root.setContentsMargins(8,7,8,7); root.setSpacing(6)
        row=QGridLayout(); self.url_edit=QLineEdit(); self.url_edit.setPlaceholderText("粘贴 B站 BV、AV、b23.tv 链接或分享文本"); self.clear_url_button,self.paste_url_button=create_url_action_buttons(self.url_edit); self.analyze_button=QPushButton("分析稿件"); self.analyze_button.clicked.connect(self._analyze); self.stop_analysis_button=QPushButton("停止分析"); self.stop_analysis_button.setVisible(False); self.stop_analysis_button.setProperty("danger",True); self.stop_analysis_button.clicked.connect(self.cancel); row.addWidget(QLabel("网址"),0,0); row.addWidget(self.url_edit,0,1); row.addWidget(self.clear_url_button,0,2); row.addWidget(self.paste_url_button,0,3); row.addWidget(self.analyze_button,0,4); row.addWidget(self.stop_analysis_button,0,5); row.setColumnStretch(1,1); root.addLayout(row)
        path=QGridLayout(); self.path_edit=QLineEdit(); browse=QPushButton("选择..."); browse.clicked.connect(self._browse); self.classify_check=QCheckBox("按平台分类保存"); path.addWidget(QLabel("保存到"),0,0); path.addWidget(self.path_edit,0,1); path.addWidget(browse,0,2); path.addWidget(self.classify_check,0,3); path.setColumnStretch(1,1); root.addLayout(path)
        info=QGroupBox("稿件与分P"); info_layout=QGridLayout(info); self.title_label=QLabel("尚未分析稿件"); self.title_label.setWordWrap(True); self.meta_label=QLabel(); self.parts_table=QTableWidget(0,4); self.parts_table.setHorizontalHeaderLabels(["下载","P","分P标题","时长"]); self.parts_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.parts_table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.parts_table.verticalHeader().setVisible(False); self.parts_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch); self.parts_table.setMinimumHeight(125); info_layout.addWidget(self.title_label,0,0); info_layout.addWidget(self.meta_label,1,0); info_layout.addWidget(self.parts_table,2,0); root.addWidget(info)
        options=QGroupBox("下载选项（自研引擎，无转码）"); grid=QGridLayout(options); self.video_quality=QComboBox(); self.video_codec=QComboBox(); [self.video_codec.addItem(label,value) for label,value in (("AVC / H.264","avc"),("HEVC / H.265","hevc"),("AV1","av1"))]; self.audio_quality=QComboBox(); grid.addWidget(QLabel("画质"),0,0); grid.addWidget(self.video_quality,0,1); grid.addWidget(QLabel("编码"),0,2); grid.addWidget(self.video_codec,0,3); grid.addWidget(QLabel("音质"),0,4); grid.addWidget(self.audio_quality,0,5)
        self.filename_template=QLineEdit("{title} P{page} {part_title} [{bvid}]"); self.filename_template.textChanged.connect(self._preview); grid.addWidget(QLabel("命名模板"),1,0); grid.addWidget(self.filename_template,1,1,1,5); tokens=template_button_widget(self.filename_template,(("标题","{title}"),("BV号","{bvid}"),("AV号","{aid}"),("UP主","{uploader}"),("P号","{page}"),("分P标题","{part_title}"),("发布日期","{upload_date}"),("下载日期","{download_date}"))); grid.addWidget(tokens,2,1,1,5)
        self.cover_check=QCheckBox("封面 JPG"); self.subtitle_check=QCheckBox("字幕 SRT"); self.danmaku_check=QCheckBox("弹幕 ASS"); self.metadata_check=QCheckBox("元数据 NFO"); extras=QHBoxLayout(); [extras.addWidget(item) for item in (self.cover_check,self.subtitle_check,self.danmaku_check,self.metadata_check)]; extras.addStretch(); grid.addLayout(extras,3,1,1,5)
        self.subtitle_tree=QTreeWidget(); self.subtitle_tree.setHeaderLabels(["字幕语言（可多选）"]); self.subtitle_tree.setMaximumHeight(82); self.subtitle_tree.setVisible(False); grid.addWidget(self.subtitle_tree,4,1,1,5)
        self.preview_label=QLabel("预览：等待分析"); self.preview_label.setWordWrap(True); grid.addWidget(self.preview_label,5,1,1,5); grid.setColumnStretch(1,1); root.addWidget(options)
        controls=QGridLayout(); self.download_button=QPushButton("开始下载"); self.download_button.setEnabled(False); self.download_button.clicked.connect(self._download); self.cancel_button=QPushButton("取消"); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(self.cancel); self.open_folder_button=QPushButton("打开保存目录"); self.open_folder_button.setProperty("secondary",True); self.open_folder_button.clicked.connect(self._open_output); self.total_progress=QProgressBar(); self.total_progress.setFormat("总任务 %p%"); self.stage_progress=QProgressBar(); self.stage_progress.setFormat("当前阶段 %p%"); controls.addWidget(self.download_button,0,0); controls.addWidget(self.cancel_button,0,1); controls.addWidget(self.open_folder_button,0,2); controls.addWidget(self.total_progress,0,3); controls.addWidget(self.stage_progress,0,4); controls.setColumnStretch(3,1); controls.setColumnStretch(4,1); root.addLayout(controls); self.progress_label=QLabel("就绪"); root.addWidget(self.progress_label); self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000); self.log.setPlaceholderText("B站分析、分片下载、附属文件和无转码合并日志"); root.addWidget(self.log,1)

    def _apply_settings(self): self.path_edit.setText(str(self.settings.resolved_save_path)); self.classify_check.setChecked(self.settings.classify_by_platform)
    def _request(self)->BilibiliDownloadRequest:
        if not self.url_edit.text().strip(): raise ValueError("请先粘贴 B站视频链接或分享文本")
        if not self.path_edit.text().strip(): raise ValueError("请选择保存目录")
        pages=[]
        for row in range(self.parts_table.rowCount()):
            if self.parts_table.item(row,0).checkState()==Qt.Checked: pages.append(int(self.parts_table.item(row,1).text()))
        if self.media and not pages: raise ValueError("请至少勾选一个分P")
        template=self.filename_template.text().strip() or "{title} P{page} {part_title} [{bvid}]"; render_filename_template(template,self._values())
        subtitles=[self.subtitle_tree.topLevelItem(i).data(0,Qt.UserRole) for i in range(self.subtitle_tree.topLevelItemCount()) if self.subtitle_tree.topLevelItem(i).checkState(0)==Qt.Checked]
        if self.media and self.subtitle_check.isChecked() and not subtitles: raise ValueError("已启用字幕下载，请至少选择一种字幕")
        cookie_file=self.settings.bilibili_cookie_file or self.settings.cookie_file
        return BilibiliDownloadRequest(self.url_edit.text().strip(),Path(self.path_edit.text().strip()).expanduser(),pages,self.video_quality.currentData(),self.video_codec.currentData(),self.audio_quality.currentData(),template,self.classify_check.isChecked(),cookie_file,self.settings.proxy,self.settings.timeout,self.cover_check.isChecked(),self.subtitle_check.isChecked(),subtitles,self.danmaku_check.isChecked(),self.metadata_check.isChecked(),self.media)
    def _analyze(self):
        if self.thread:return
        try: request=self._request()
        except ValueError as exc: QMessageBox.warning(self,"无法分析",str(exc)); return
        self.media=None; self.parts_table.setRowCount(0); self._analysis_running=True; self._set_busy(True,"正在分析 B站稿件..."); self._analysis_progress()
        if not self.settings.bilibili_cookie_file and self.settings.cookie_file: self.log.appendPlainText("B站专用 Cookie 未设置，正在使用 YouTube / X 通用 cookies.txt")
        worker=BilibiliAnalyzeWorker(request); self._start(worker,worker.run); worker.completed.connect(self._analysis_complete); worker.failed.connect(self._failed)
    def _download(self):
        if self.thread:return
        try: request=self._request()
        except ValueError as exc: QMessageBox.warning(self,"无法下载",str(exc)); return
        self._analysis_running=False; self._set_busy(True,"正在启动 B站下载..."); worker=BilibiliDownloadWorker(request); self._start(worker,worker.run); worker.progress.connect(self._progress); worker.completed.connect(self._complete)
    def _start(self,worker,entry):
        thread=QThread(self); self.thread=thread; self.worker=worker; worker.moveToThread(thread); thread.started.connect(entry); self.cancel_requested.connect(worker.cancel); worker.log.connect(self.log.appendPlainText); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater); thread.finished.connect(self._thread_finished); thread.start()
    def _analysis_complete(self,media):
        self.media=media; self.title_label.setText(media.title); self.meta_label.setText(f"UP主：{media.uploader}    BV：{media.bvid}    AV：{media.aid}    分P：{len(media.parts)}"); self.parts_table.setRowCount(len(media.parts))
        for row,part in enumerate(media.parts):
            check=QTableWidgetItem(); check.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable); check.setCheckState(Qt.Checked if part.selected else Qt.Unchecked); self.parts_table.setItem(row,0,check); self.parts_table.setItem(row,1,QTableWidgetItem(str(part.page))); self.parts_table.setItem(row,2,QTableWidgetItem(part.title)); self.parts_table.setItem(row,3,QTableWidgetItem(f"{int(part.duration or 0)//60:02d}:{int(part.duration or 0)%60:02d}"))
        first=next((p for p in media.parts if p.selected),media.parts[0]); self.video_quality.clear(); seen=set()
        for stream in sorted(first.video_streams,key=lambda x:x.stream_id,reverse=True):
            if stream.stream_id not in seen:self.video_quality.addItem(stream.label,stream.stream_id);seen.add(stream.stream_id)
        self.audio_quality.clear();
        for stream in sorted(first.audio_streams,key=lambda x:x.stream_id,reverse=True): self.audio_quality.addItem(stream.label,stream.stream_id)
        self.subtitle_tree.clear()
        for subtitle in first.subtitles:
            item=QTreeWidgetItem([f"{subtitle.name} ({subtitle.language})"]); item.setData(0,Qt.UserRole,subtitle.language); item.setFlags(item.flags()|Qt.ItemIsUserCheckable); item.setCheckState(0,Qt.Unchecked); self.subtitle_tree.addTopLevelItem(item)
        self.subtitle_tree.setVisible(bool(first.subtitles)); self.subtitle_check.setEnabled(bool(first.subtitles)); self._preview(); self._reset_progress(); self._set_busy(False,"分析完成")
    def _values(self):
        part=next((p for p in self.media.parts if p.selected),self.media.parts[0]) if self.media else None; media=self.media
        return {"title":media.title if media else "视频标题","id":media.bvid if media else "BV号","bvid":media.bvid if media else "BV号","aid":str(media.aid) if media else "AV号","uploader":media.uploader if media else "UP主","author":media.uploader if media else "UP主","channel":media.uploader if media else "UP主","platform":"哔哩哔哩","upload_date":media.upload_date if media else "","page":str(part.page) if part else "1","part_title":part.title if part else "分P标题"}
    def _preview(self):
        try:self.preview_label.setText("预览："+render_filename_template(self.filename_template.text() or "{title} P{page} {part_title} [{bvid}]",self._values())+".mp4")
        except ValueError as exc:self.preview_label.setText(f"模板错误：{exc}")
    def _progress(self,item:TaskProgress):
        if item.total_percent is not None:self.total_progress.setRange(0,100);self.total_progress.setValue(round(item.total_percent))
        if item.stage_indeterminate or item.stage_percent is None:self.stage_progress.setRange(0,0)
        else:self.stage_progress.setRange(0,100);self.stage_progress.setValue(round(item.stage_percent))
        self.progress_label.setText(f"{item.stage} {item.current_item}".strip())
    def _complete(self,result:TaskResult):
        self._reset_progress(); self._set_busy(False,result.message)
        if result.success: self.log.appendPlainText("下载完成\n输出文件：\n"+"\n".join(str(p) for p in result.output_files))
        elif result.error_category!="已取消": QMessageBox.critical(self,f"B站下载失败：{result.error_category}",result.message)
    def _failed(self,category,message): self.media=None; self._reset_progress(); self._set_busy(False,message); QMessageBox.critical(self,f"B站分析失败：{category}",message)
    def _analysis_progress(self): self.total_progress.setRange(0,0);self.stage_progress.setRange(0,0)
    def _reset_progress(self): self.total_progress.setRange(0,100);self.total_progress.setValue(0);self.stage_progress.setRange(0,100);self.stage_progress.setValue(0)
    def _set_busy(self,busy,text): self.analyze_button.setEnabled(not busy);self.download_button.setEnabled(not busy and self.media is not None);self.cancel_button.setEnabled(busy);self.stop_analysis_button.setVisible(busy and self._analysis_running);self.progress_label.setText(text)
    def _thread_finished(self): self.thread=None;self.worker=None;self._analysis_running=False;self._set_busy(False,self.progress_label.text())
    def _browse(self):
        path=QFileDialog.getExistingDirectory(self,"选择保存目录",self.path_edit.text());
        if path:self.path_edit.setText(path)
    def _open_output(self):
        path=Path(self.path_edit.text().strip()).expanduser()
        path.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
    def cancel(self):
        if self.worker:self.cancel_button.setEnabled(False);self.stop_analysis_button.setEnabled(False);self.progress_label.setText("正在取消...");self.cancel_requested.emit()
    def is_busy(self):return self.thread is not None
    def shutdown(self):
        if self.thread:self.cancel_requested.emit();self.thread.quit();self.thread.wait(3000)
