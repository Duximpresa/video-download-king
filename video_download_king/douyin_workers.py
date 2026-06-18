from __future__ import annotations

import shutil
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from .douyin import DouyinService, resolve_douyin_output_dir
from .errors import categorize_error
from .models import (
    DouyinDownloadRequest,
    DouyinMediaInfo,
    DownloadRequest,
    MediaInfo,
    TaskProgress,
    TaskResult,
)
from .processes import ProcessCancelled
from .platforms import extract_douyin_url
from .utils import unique_path
from .ytdlp import YtDlpService


def _from_ytdlp(media: MediaInfo) -> DouyinMediaInfo:
    return DouyinMediaInfo(
        webpage_url=media.webpage_url,
        media_id=media.media_id,
        title=media.title,
        author=media.channel,
        upload_date=media.upload_date,
        duration=media.duration,
        thumbnail=media.thumbnail,
        media_type="video",
    )


def _yt_request(request: DouyinDownloadRequest, media: DouyinMediaInfo) -> DownloadRequest:
    quality = {
        "highest": "best",
        "lowest": "worst",
        "1080p": "1080p",
        "720p": "720p",
        "540p": "custom",
    }[request.quality]
    return DownloadRequest(
        url=media.webpage_url,
        output_dir=request.output_dir,
        media_title=media.title,
        media_id=media.media_id,
        media_channel=media.author,
        media_upload_date=media.upload_date,
        media_platform="Douyin",
        filename_template=request.filename_template,
        classify_by_platform=False,
        mode="video_audio",
        quality_preset=quality,
        custom_height=540 if request.quality == "540p" else None,
        proxy=request.proxy,
        cookie_file=request.cookie_file,
        timeout=request.timeout,
        download_thumbnail=request.download_thumbnail,
        transcode=request.transcode,
    )


class DouyinAnalyzeWorker(QObject):
    log = Signal(str)
    completed = Signal(object)
    failed = Signal(str, str)
    engine_fallback_requested = Signal(str, str)
    finished = Signal()

    def __init__(self, request: DouyinDownloadRequest) -> None:
        super().__init__()
        self.request = request
        self.native = DouyinService()
        self.ytdlp = YtDlpService()
        self._decision_event = Event()
        self._allow_fallback = False

    @Slot()
    def run(self) -> None:
        try:
            engine = self.request.download_engine
            try:
                media = self._analyze_with(engine)
            except ProcessCancelled:
                raise
            except Exception as exc:
                other = "yt_dlp" if engine == "native" else "native"
                self._decision_event.clear()
                self.engine_fallback_requested.emit(other, str(exc))
                self._decision_event.wait()
                if not self._allow_fallback:
                    raise
                self.log.emit(f"用户已确认，切换到 {'yt-dlp' if other == 'yt_dlp' else '自研引擎'} 分析")
                media = self._analyze_with(other)
                self.request.download_engine = other
            self.completed.emit(media)
        except ProcessCancelled:
            self.failed.emit("已取消", "任务已取消")
        except Exception as exc:
            text = str(exc)
            self.failed.emit(categorize_error(text), text)
        finally:
            self.finished.emit()

    def _analyze_with(self, engine: str) -> DouyinMediaInfo:
        if engine == "native":
            return self.native.analyze(self.request, self.log.emit)
        url = extract_douyin_url(self.request.url) or self.request.url
        return _from_ytdlp(
            self.ytdlp.analyze(
                url,
                proxy=self.request.proxy,
                cookie_file=self.request.cookie_file,
                timeout=self.request.timeout,
                on_log=self.log.emit,
            )
        )

    @Slot()
    def cancel(self) -> None:
        self._allow_fallback = False
        self._decision_event.set()
        self.native.cancel()
        self.ytdlp.cancel()

    def resolve_engine_fallback(self, allow: bool) -> None:
        self._allow_fallback = allow
        self._decision_event.set()


class DouyinDownloadWorker(QObject):
    log = Signal(str)
    progress = Signal(object)
    completed = Signal(object)
    engine_fallback_requested = Signal(str, str)
    finished = Signal()

    def __init__(self, request: DouyinDownloadRequest) -> None:
        super().__init__()
        self.request = request
        self.native = DouyinService()
        self.ytdlp = YtDlpService()
        self._decision_event = Event()
        self._allow_engine_fallback = False
        self._last_total_percent = 0.0

    @Slot()
    def run(self) -> None:
        try:
            engine = self.request.download_engine
            try:
                files = self._run_engine(engine)
            except ProcessCancelled:
                raise
            except Exception as exc:
                if self.request.media and self.request.media.media_type == "gallery":
                    raise
                self._decision_event.clear()
                other = "yt_dlp" if engine == "native" else "native"
                self.engine_fallback_requested.emit(other, str(exc))
                self._decision_event.wait()
                if not self._allow_engine_fallback:
                    raise
                self.log.emit(f"用户已确认，切换到 {'yt-dlp' if other == 'yt_dlp' else '自研引擎'} 重试")
                files = self._run_engine(other)

            self.progress.emit(TaskProgress("完成", 100, 100))
            self.completed.emit(
                TaskResult(
                    True,
                    "下载完成",
                    files[0] if files else None,
                    files,
                )
            )
        except ProcessCancelled:
            self.completed.emit(TaskResult(False, "任务已取消", error_category="已取消"))
        except Exception as exc:
            text = str(exc)
            self.completed.emit(TaskResult(False, text, error_category=categorize_error(text)))
        finally:
            self.finished.emit()

    def _run_engine(self, engine: str) -> list[Path]:
        if engine == "native":
            if (
                self.request.media is None
                or (
                    self.request.media.media_type == "video"
                    and not self.request.media.video_assets
                )
            ):
                self.request.media = self.native.analyze(self.request, self.log.emit)
            files = self.native.download(self.request, self._native_progress, self.log.emit)
        else:
            files = self._download_ytdlp()
        return files

    def _native_progress(self, progress: TaskProgress) -> None:
        if progress.total_percent is not None:
            self._last_total_percent = max(self._last_total_percent, progress.total_percent)
            progress.total_percent = self._last_total_percent
        self.progress.emit(progress)

    def _download_ytdlp(self) -> list[Path]:
        media = self.request.media
        if not media:
            media = _from_ytdlp(
                self.ytdlp.analyze(
                    self.request.url,
                    proxy=self.request.proxy,
                    cookie_file=self.request.cookie_file,
                    timeout=self.request.timeout,
                    on_log=self.log.emit,
                )
            )
            self.request.media = media
        if media.media_type != "video":
            raise ValueError("yt-dlp 引擎不支持抖音图集，请使用自研引擎")

        output_dir = resolve_douyin_output_dir(self.request, media.author)
        output_dir.mkdir(parents=True, exist_ok=True)
        staging = output_dir / f".vdk-ytdlp-{media.media_id}-{time.time_ns()}"
        staging.mkdir(parents=True)
        try:
            request = _yt_request(self.request, media)

            def on_progress(progress: TaskProgress) -> None:
                self.progress.emit(progress)

            artifacts = self.ytdlp.download(request, staging, on_progress, self.log.emit)
            staged = [
                path
                for path in [
                    artifacts.media_path,
                    *artifacts.cover_paths,
                    *artifacts.subtitle_paths,
                ]
                if path is not None
            ]
            if not staged:
                raise RuntimeError("yt-dlp 未生成输出文件")
            final: list[Path] = []
            for path in staged:
                target = unique_path(output_dir / path.name)
                path.replace(target)
                final.append(target)
            return final
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @Slot()
    def cancel(self) -> None:
        self._allow_engine_fallback = False
        self._decision_event.set()
        self.native.cancel()
        self.ytdlp.cancel()

    def resolve_engine_fallback(self, allow: bool) -> None:
        self._allow_engine_fallback = allow
        self._decision_event.set()
