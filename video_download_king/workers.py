from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .errors import categorize_error
from .models import DownloadRequest, MediaInfo, TaskProgress, TaskResult
from .platforms import validate_first_version_url
from .processes import ProcessCancelled
from .transcode import FFmpegService
from .ytdlp import YtDlpService


class AnalyzeWorker(QObject):
    log = Signal(str)
    completed = Signal(object)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, request: DownloadRequest) -> None:
        super().__init__()
        self.request = request
        self.service = YtDlpService()

    @Slot()
    def run(self) -> None:
        try:
            media: MediaInfo = self.service.analyze(
                self.request.url,
                proxy=self.request.proxy,
                cookie_file=self.request.cookie_file,
                cookie_browser=self.request.cookie_browser,
                timeout=self.request.timeout,
                on_log=self.log.emit,
            )
            self.completed.emit(media)
        except Exception as exc:
            text = str(exc)
            self.failed.emit(categorize_error(text), text)
        finally:
            self.finished.emit()

    @Slot()
    def cancel(self) -> None:
        self.service.cancel()


class DownloadWorker(QObject):
    log = Signal(str)
    progress = Signal(object)
    completed = Signal(object)
    finished = Signal()

    def __init__(self, request: DownloadRequest) -> None:
        super().__init__()
        self.request = request
        self.downloader = YtDlpService()
        self.transcoder = FFmpegService()

    @Slot()
    def run(self) -> None:
        try:
            platform = validate_first_version_url(self.request.url)
            output_dir = self.request.output_dir
            if self.request.classify_by_platform:
                output_dir = output_dir / platform
            self.progress.emit(TaskProgress(stage="准备", percent=0, message="正在准备下载"))
            source = self.downloader.download(
                self.request,
                output_dir,
                self.progress.emit,
                self.log.emit,
            )
            result_path = source
            if self.request.transcode.enabled and self.request.mode != "audio":
                self.progress.emit(TaskProgress(stage="检测", percent=0, message="正在检查媒体编码"))
                self.transcoder.detect_encoder(self.log.emit)
                result_path = self.transcoder.convert(
                    source,
                    self.request.transcode,
                    self.progress.emit,
                    self.log.emit,
                )
            self.progress.emit(TaskProgress(stage="完成", percent=100))
            self.completed.emit(TaskResult(True, "下载完成", result_path))
        except ProcessCancelled:
            self.completed.emit(TaskResult(False, "任务已取消", error_category="已取消"))
        except Exception as exc:
            text = str(exc)
            self.completed.emit(TaskResult(False, text, error_category=categorize_error(text)))
        finally:
            self.finished.emit()

    @Slot()
    def cancel(self) -> None:
        self.downloader.cancel()
        self.transcoder.cancel()

