from __future__ import annotations

import json
import re
from collections.abc import Callable
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
    r"^__VDK_PROGRESS__"
    r"(?P<percent>[^|]*)\|(?P<speed>[^|]*)\|(?P<eta>[^|]*)\|(?P<total>.*)$"
)
FINAL_PREFIX = "__VDK_FILE__"


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
            "--no-overwrites",
            "--format",
            selector,
            "--output",
            template,
            "--progress-template",
            "download:__VDK_PROGRESS__%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(progress._total_bytes_str)s",
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
        if request.download_subtitles:
            args.extend(
                [
                    "--write-auto-subs" if request.use_automatic_subtitles else "--write-subs",
                    "--sub-langs",
                    request.subtitle_languages,
                    "--sub-format",
                    "srt/best",
                    "--convert-subs",
                    "srt",
                ]
            )
        return args

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

        def handle_line(line: str) -> None:
            nonlocal final_path
            match = PROGRESS_RE.match(line)
            if match:
                percent_text = match.group("percent").strip().rstrip("%")
                try:
                    percent = float(percent_text)
                except ValueError:
                    percent = None
                on_progress(
                    TaskProgress(
                        stage="下载",
                        percent=percent,
                        speed=match.group("speed").strip(),
                        eta=match.group("eta").strip(),
                        total=match.group("total").strip(),
                    )
                )
            elif line.startswith(FINAL_PREFIX):
                final_path = Path(line[len(FINAL_PREFIX) :])
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
        optional_args = self._optional_args(request)
        if optional_args:
            output_template = main_args[main_args.index("--output") + 1]
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
                on_log(f"部分封面或字幕未能下载，主视频不受影响：{diagnostic or 'yt-dlp 返回非零状态'}")
        cover_paths = [
            path for path in output_dir.glob(f"{media_path.stem}.*")
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        ]
        subtitle_paths = [
            path for path in output_dir.glob(f"{media_path.stem}.*")
            if path.suffix.lower() in {".srt", ".vtt", ".ass"}
        ]
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
