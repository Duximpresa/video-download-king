from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from .errors import categorize_error
from .models import DownloadRequest, MediaInfo, TaskProgress, TaskResult
from .platforms import validate_first_version_url
from .processes import ProcessCancelled
from .transcode import FFmpegService, HardwareEncodingError
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
    gpu_fallback_requested = Signal(str)
    finished = Signal()

    def __init__(self, request: DownloadRequest) -> None:
        super().__init__()
        self.request = request
        self.downloader = YtDlpService()
        self.transcoder = FFmpegService()
        self._fallback_event = Event()
        self._allow_fallback = False

    @Slot()
    def run(self) -> None:
        try:
            platform = validate_first_version_url(self.request.url)
            output_dir = self.request.output_dir
            if self.request.classify_by_platform:
                output_dir = output_dir / platform
            self.progress.emit(TaskProgress(stage="准备", percent=0, message="正在准备下载"))
            artifacts = self.downloader.download(
                self.request,
                output_dir,
                self.progress.emit,
                self.log.emit,
            )
            source = artifacts.media_path
            result_path = source
            if self.request.transcode.enabled and self.request.mode not in {"audio", "video_only"}:
                self.progress.emit(TaskProgress(stage="检测", percent=0, message="正在检查媒体编码"))
                try:
                    result_path = self.transcoder.convert(
                        source,
                        self.request.transcode,
                        self.progress.emit,
                        self.log.emit,
                    )
                except HardwareEncodingError as exc:
                    self._fallback_event.clear()
                    self.gpu_fallback_requested.emit(str(exc))
                    self._fallback_event.wait()
                    if not self._allow_fallback:
                        raise
                    self.log.emit("用户已确认，改用 CPU (libx264) 重试")
                    self.request.transcode.processor = "cpu"
                    result_path = self.transcoder.convert(
                        source,
                        self.request.transcode,
                        self.progress.emit,
                        self.log.emit,
                    )
            artifacts.cover_paths = self._rename_sidecars(source, result_path, artifacts.cover_paths)
            artifacts.subtitle_paths = self._rename_sidecars(source, result_path, artifacts.subtitle_paths)
            if self.request.embed_thumbnail and artifacts.cover_paths and self.request.mode != "audio":
                self.transcoder.embed_cover(result_path, artifacts.cover_paths[0], self.log.emit)
                if not self.request.download_thumbnail:
                    for cover in artifacts.cover_paths:
                        cover.unlink(missing_ok=True)
                    artifacts.cover_paths = []
            elif self.request.embed_thumbnail and not artifacts.cover_paths:
                self.log.emit("未找到可用封面，已跳过嵌入")
            self.progress.emit(TaskProgress(stage="完成", percent=100))
            output_files = [result_path, *artifacts.cover_paths, *artifacts.subtitle_paths]
            self.completed.emit(TaskResult(True, "下载完成", result_path, output_files))
        except ProcessCancelled:
            self.completed.emit(TaskResult(False, "任务已取消", error_category="已取消"))
        except Exception as exc:
            text = str(exc)
            self.completed.emit(TaskResult(False, text, error_category=categorize_error(text)))
        finally:
            self.finished.emit()

    @Slot()
    def cancel(self) -> None:
        self._allow_fallback = False
        self._fallback_event.set()
        self.downloader.cancel()
        self.transcoder.cancel()

    def resolve_gpu_fallback(self, allow: bool) -> None:
        self._allow_fallback = allow
        self._fallback_event.set()

    @staticmethod
    def _rename_sidecars(source: Path, result: Path, paths: list[Path]) -> list[Path]:
        if source.stem == result.stem:
            return paths
        renamed: list[Path] = []
        for path in paths:
            remainder = path.name[len(source.stem) :] if path.name.startswith(source.stem) else path.suffix
            target = result.with_name(f"{result.stem}{remainder}")
            if target.exists():
                target = target.with_name(f"{target.stem} (1){target.suffix}")
            path.replace(target)
            renamed.append(target)
        return renamed
