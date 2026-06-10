from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .formats import format_selector
from .models import DownloadArtifacts, DownloadRequest, MediaInfo, TaskProgress
from .paths import deno_path, ffmpeg_dir, yt_dlp_path
from .platforms import validate_first_version_url
from .processes import ProcessRunner
from .utils import render_filename_template, unique_media_stem


ProgressCallback = Callable[[TaskProgress], None]
LogCallback = Callable[[str], None]

PROGRESS_RE = re.compile(
    r"^\s*__VDK_PROGRESS__\s*"
    r"(?P<percent>[^|]*)\|(?P<speed>[^|]*)\|(?P<eta>[^|]*)\|(?P<total_text>[^|]*)\|"
    r"(?P<downloaded>[^|]*)\|(?P<total_bytes>[^|]*)\|(?P<estimated>[^|]*)\|(?P<format_id>.*)$"
)
FINAL_PREFIX = "__VDK_FILE__"


def _progress_int(value: str) -> int | None:
    value = value.strip()
    return int(value) if value.isdigit() else None


@dataclass(slots=True)
class DownloadProgressTracker:
    expected_streams: int = 1
    streams: dict[str, tuple[int, int | None]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    last_total_percent: float = 0.0

    def update(self, match: re.Match[str]) -> TaskProgress:
        format_id = match.group("format_id").strip() or "media"
        downloaded = _progress_int(match.group("downloaded")) or 0
        total_bytes = _progress_int(match.group("total_bytes")) or _progress_int(match.group("estimated"))
        if format_id not in self.order:
            self.order.append(format_id)
        self.streams[format_id] = (downloaded, total_bytes)
        try:
            stage_percent = max(0.0, min(100.0, float(match.group("percent").strip().rstrip("%"))))
        except ValueError:
            stage_percent = None
        known = [(done, total) for done, total in self.streams.values() if total and total > 0]
        if len(known) >= self.expected_streams:
            media_percent = sum(min(done, total) for done, total in known) / sum(total for _, total in known) * 100
        else:
            index = min(self.order.index(format_id), self.expected_streams - 1)
            media_percent = (index + (stage_percent or 0) / 100) / self.expected_streams * 100
        self.last_total_percent = max(self.last_total_percent, min(100.0, media_percent))
        return TaskProgress(
            stage="下载",
            total_percent=self.last_total_percent,
            stage_percent=stage_percent,
            current_item=f"格式 {format_id}",
            speed=match.group("speed").strip(),
            eta=match.group("eta").strip(),
            total=match.group("total_text").strip(),
            downloaded_bytes=downloaded,
            total_bytes=total_bytes,
        )


class YtDlpService:
    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self.runner = runner or ProcessRunner()

    @staticmethod
    def _common_args(request: DownloadRequest) -> list[str]:
        args = [
            "--no-playlist",
            "--socket-timeout",
            str(request.timeout),
            "--ffmpeg-location",
            str(ffmpeg_dir()),
            "--windows-filenames",
            "--encoding",
            "utf-8",
        ]
        if deno_path().exists():
            args.extend(["--js-runtimes", f"deno:{deno_path()}"])
        proxy = request.proxy.url()
        if proxy:
            args.extend(["--proxy", proxy])
        if request.cookie_file:
            args.extend(["--cookies", request.cookie_file])
        elif request.cookie_browser:
            args.extend(["--cookies-from-browser", request.cookie_browser])
        return args

    def analyze(
        self,
        url: str,
        *,
        proxy=None,
        cookie_file: str = "",
        cookie_browser: str = "",
        timeout: int = 30,
        on_log: LogCallback | None = None,
    ) -> MediaInfo:
        validate_first_version_url(url)
        request = DownloadRequest(
            url=url,
            output_dir=Path("."),
            proxy=proxy or DownloadRequest(url="", output_dir=Path(".")).proxy,
            cookie_file=cookie_file,
            cookie_browser=cookie_browser,
            timeout=timeout,
        )
        args = [
            yt_dlp_path(),
            *self._common_args(request),
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            url,
        ]
        code, output = self.runner.run(args, capture=True)
        if code:
            diagnostic = "\n".join(line for line in output.splitlines() if line.strip() not in {"", "null"})
            raise RuntimeError(diagnostic or f"yt-dlp 分析失败，退出码 {code}")
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"无法解析 yt-dlp 返回的数据：{exc}") from exc
        media = MediaInfo.from_json(data)
        if media.is_live:
            raise ValueError("第一版暂不支持直播下载")
        return media

    def build_download_args(
        self,
        request: DownloadRequest,
        output_dir: Path,
        *,
        include_optional: bool = True,
    ) -> list[str]:
        if request.mode == "cover":
            return self.build_cover_args(request, output_dir)
        selector = format_selector(request)
        template = self._output_template(request, output_dir)
        args = [
            str(yt_dlp_path()),
            *self._common_args(request),
            "--newline",
            "--progress",
            "--no-overwrites",
            "--format",
            selector,
            "--output",
            template,
            "--progress-template",
            "download:__VDK_PROGRESS__%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(progress._total_bytes_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(info.format_id)s",
            "--print",
            f"after_move:{FINAL_PREFIX}%(filepath)s",
        ]
        if request.mode in {"video_audio", "advanced"}:
            args.extend(["--merge-output-format", "mkv/mp4"])
        elif request.mode == "audio" and request.audio_output != "original":
            args.extend(["--extract-audio", "--audio-format", request.audio_output])
        if include_optional:
            args.extend(self._optional_args(request))
        args.append(request.url)
        return args

    @staticmethod
    def _output_template(request: DownloadRequest, output_dir: Path) -> str:
        if request.media_title and request.media_id:
            stem = render_filename_template(
                request.filename_template,
                {
                    "title": request.media_title,
                    "id": request.media_id,
                    "channel": request.media_channel,
                    "platform": request.media_platform,
                    "upload_date": request.media_upload_date,
                },
            )
            stem = unique_media_stem(output_dir, stem)
            return str(output_dir / f"{stem}.%(ext)s")
        return str(output_dir / "%(title).180B [%(id)s].%(ext)s")

    def build_cover_args(self, request: DownloadRequest, output_dir: Path) -> list[str]:
        return [
            str(yt_dlp_path()),
            *self._common_args(request),
            "--newline",
            "--no-overwrites",
            "--skip-download",
            "--write-thumbnail",
            "--output",
            self._output_template(request, output_dir),
            request.url,
        ]

    @staticmethod
    def _optional_args(request: DownloadRequest) -> list[str]:
        args: list[str] = []
        if request.download_thumbnail:
            args.append("--write-thumbnail")
        return args

    @staticmethod
    def build_subtitle_commands(
        request: DownloadRequest,
        output_template: str,
    ) -> list[tuple[str, list[str]]]:
        commands: list[tuple[str, list[str]]] = []
        for kind, flag in (("manual", "--write-subs"), ("automatic", "--write-auto-subs")):
            languages = [item.language for item in request.subtitle_selections if item.kind == kind]
            if not languages:
                continue
            args = [
                str(yt_dlp_path()),
                *YtDlpService._common_args(request),
                "--skip-download",
                "--ignore-errors",
                "--output",
                output_template,
                flag,
                "--sub-langs",
                ",".join(languages),
                "--sub-format",
                f"{request.subtitle_format}/best",
            ]
            if request.subtitle_format == "srt":
                args.extend(["--convert-subs", "srt"])
            args.append(request.url)
            commands.append((kind, args))
        return commands

    def download(
        self,
        request: DownloadRequest,
        output_dir: Path,
        on_progress: ProgressCallback,
        on_log: LogCallback,
    ) -> DownloadArtifacts:
        output_dir.mkdir(parents=True, exist_ok=True)
        if request.mode == "cover":
            return self._download_cover(request, output_dir, on_log)
        final_path: Path | None = None
        expected_streams = 2 if request.mode == "video_audio" or (
            request.mode == "advanced" and request.audio_format_id
        ) else 1
        tracker = DownloadProgressTracker(expected_streams=expected_streams)

        def handle_line(line: str) -> None:
            nonlocal final_path
            match = PROGRESS_RE.match(line)
            if match:
                on_progress(tracker.update(match))
            elif line.startswith(FINAL_PREFIX):
                final_path = Path(line[len(FINAL_PREFIX) :])
            elif "[Merger]" in line or "[VideoRemuxer]" in line or "[ExtractAudio]" in line:
                on_progress(
                    TaskProgress(
                        stage="合并",
                        total_percent=100,
                        stage_indeterminate=True,
                        message=line,
                    )
                )
                on_log(line)
            else:
                on_log(line)

        main_args = self.build_download_args(request, output_dir, include_optional=False)
        code, _ = self.runner.run(main_args, on_line=handle_line)
        if code:
            raise RuntimeError(f"yt-dlp 下载失败，退出码 {code}")
        if final_path and final_path.exists():
            media_path = final_path
        else:
            candidates = sorted(
                (path for path in output_dir.glob("*") if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".srt", ".vtt", ".ass"}),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                raise RuntimeError("下载完成，但未找到输出文件")
            media_path = candidates[0]
        output_template = main_args[main_args.index("--output") + 1]
        optional_args = self._optional_args(request)
        if optional_args:
            on_progress(TaskProgress(stage="封面", total_percent=0, stage_percent=0, message="正在下载封面"))
            sidecar_command = [
                yt_dlp_path(),
                *self._common_args(request),
                "--skip-download",
                "--ignore-errors",
                "--output",
                output_template,
                *optional_args,
                request.url,
            ]
            sidecar_code, sidecar_output = self.runner.run(sidecar_command, capture=True)
            diagnostic = "\n".join(
                line for line in sidecar_output.splitlines() if "ERROR:" in line or "WARNING:" in line
            )
            if sidecar_code or diagnostic:
                on_log(f"封面未能下载，主视频不受影响：{diagnostic or 'yt-dlp 返回非零状态'}")
            on_progress(TaskProgress(stage="封面", total_percent=100, stage_percent=100, message="封面处理完成"))
        for kind, subtitle_command in self.build_subtitle_commands(request, output_template):
            label = "人工字幕" if kind == "manual" else "自动字幕"
            on_progress(TaskProgress(stage="字幕", total_percent=0, stage_percent=0, message=f"正在下载{label}"))
            subtitle_code, subtitle_output = self.runner.run(subtitle_command, capture=True)
            diagnostic = "\n".join(
                line for line in subtitle_output.splitlines() if "ERROR:" in line or "WARNING:" in line
            )
            if subtitle_code or diagnostic:
                on_log(f"{label}部分或全部下载失败，主视频不受影响：{diagnostic or 'yt-dlp 返回非零状态'}")
            on_progress(TaskProgress(stage="字幕", total_percent=100, stage_percent=100, message=f"{label}处理完成"))
        cover_paths = [
            path for path in output_dir.iterdir()
            if path.name.startswith(f"{media_path.stem}.")
            and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        ]
        subtitle_paths = [
            path for path in output_dir.iterdir()
            if path.name.startswith(f"{media_path.stem}.")
            and path.suffix.lower() in {".srt", ".vtt", ".ass"}
        ]
        for selection in request.subtitle_selections:
            marker = f".{selection.language}."
            if not any(marker.lower() in path.name.lower() for path in subtitle_paths):
                label = "人工字幕" if selection.kind == "manual" else "自动字幕"
                on_log(f"未生成所选{label} {selection.language}，主视频不受影响")
        return DownloadArtifacts(media_path, cover_paths, subtitle_paths)

    def _download_cover(
        self,
        request: DownloadRequest,
        output_dir: Path,
        on_log: LogCallback,
    ) -> DownloadArtifacts:
        before = {
            path.resolve()
            for path in output_dir.iterdir()
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        }
        code, output = self.runner.run(self.build_cover_args(request, output_dir), capture=True)
        if output:
            for line in output.splitlines():
                on_log(line)
        covers = sorted(
            (
                path
                for path in output_dir.iterdir()
                if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                and path.resolve() not in before
            ),
            key=lambda path: path.stat().st_mtime,
        )
        if code or not covers:
            raise RuntimeError(output or "封面下载完成，但未找到输出图片")
        return DownloadArtifacts(None, covers, [])

    def cancel(self) -> None:
        self.runner.cancel()
