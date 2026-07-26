from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from .errors import categorize_error, user_facing_error
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
        except ProcessCancelled:
            self.failed.emit("已取消", "任务已取消")
        except Exception as exc:
            text = str(exc)
            self.log.emit(text)
            self.failed.emit(categorize_error(text), user_facing_error(text))
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
            if platform not in {"YouTube", "Instagram", "TikTok", "X"}:
                raise ValueError("请使用独立的【B站下载】页面")
            output_dir = self.request.output_dir
            if self.request.classify_by_platform:
                output_dir = output_dir / platform
            use_transcode = (
                self.request.transcode.enabled
                and self.request.mode not in {"audio", "video_only", "cover"}
            )
            media_end = 70.0 if use_transcode else 85.0
            post_end = 80.0 if use_transcode else 100.0
            self.progress.emit(TaskProgress(stage="准备", total_percent=0, stage_percent=0, message="正在准备下载"))

            def download_progress(progress: TaskProgress) -> None:
                if progress.stage == "下载":
                    raw = progress.total_percent or 0
                    progress.total_percent = raw / 100 * media_end
                elif progress.stage == "合并":
                    progress.total_percent = media_end
                else:
                    raw = progress.total_percent or 0
                    progress.total_percent = media_end + raw / 100 * (post_end - media_end)
                self.progress.emit(progress)

            artifacts = self.downloader.download(
                self.request,
                output_dir,
                download_progress,
                self.log.emit,
            )
            source = artifacts.media_path
            result_path = source
            if source and use_transcode:
                self.progress.emit(
                    TaskProgress(stage="检测", total_percent=post_end, stage_indeterminate=True, message="正在检查媒体编码")
                )
                def transcode_progress(progress: TaskProgress) -> None:
                    stage_percent = progress.stage_percent or 0
                    progress.total_percent = post_end + stage_percent / 100 * (100 - post_end)
                    self.progress.emit(progress)

                try:
                    result_path = self.transcoder.convert(
                        source,
                        self.request.transcode,
                        transcode_progress,
                        self.log.emit,
                    )
                except HardwareEncodingError as exc:
                    self._fallback_event.clear()
                    self.gpu_fallback_requested.emit(str(exc))
                    self._fallback_event.wait()
                    if not self._allow_fallback:
                        raise
                    self.log.emit("用户已确认，改用 CPU (libx264) 重试")
                    self.request.transcode.video_encoder = "cpu"
                    result_path = self.transcoder.convert(
                        source,
                        self.request.transcode,
                        transcode_progress,
                        self.log.emit,
                    )
            if source and result_path:
                artifacts.cover_paths = self._rename_sidecars(source, result_path, artifacts.cover_paths)
                artifacts.subtitle_paths = self._rename_sidecars(source, result_path, artifacts.subtitle_paths)
            self.progress.emit(TaskProgress(stage="完成", total_percent=100, stage_percent=100))
            output_files = [
                path
                for path in [result_path, *artifacts.cover_paths, *artifacts.subtitle_paths]
                if path is not None
            ]
            self.completed.emit(TaskResult(True, "下载完成", result_path, output_files))
        except ProcessCancelled:
            self.completed.emit(TaskResult(False, "任务已取消", error_category="已取消"))
        except Exception as exc:
            text = str(exc)
            self.completed.emit(
                TaskResult(False, user_facing_error(text), error_category=categorize_error(text))
            )
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
