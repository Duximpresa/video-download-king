from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from .formats import format_selector
from .models import DownloadRequest, MediaInfo, TaskProgress
from .paths import deno_path, ffmpeg_dir, yt_dlp_path
from .platforms import validate_first_version_url
from .processes import ProcessRunner
from .utils import sanitize_filename, unique_media_stem


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

    def build_download_args(self, request: DownloadRequest, output_dir: Path) -> list[str]:
        selector = format_selector(request)
        if request.media_title and request.media_id:
            stem = sanitize_filename(f"{request.media_title} [{request.media_id}]")
            stem = unique_media_stem(output_dir, stem)
            template = str(output_dir / f"{stem}.%(ext)s")
        else:
            template = str(output_dir / "%(title).180B [%(id)s].%(ext)s")
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
        if request.mode != "audio":
            args.extend(["--merge-output-format", "mkv/mp4"])
        elif request.audio_output != "original":
            args.extend(["--extract-audio", "--audio-format", request.audio_output])
        args.append(request.url)
        return args

    def download(
        self,
        request: DownloadRequest,
        output_dir: Path,
        on_progress: ProgressCallback,
        on_log: LogCallback,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
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

        code, _ = self.runner.run(self.build_download_args(request, output_dir), on_line=handle_line)
        if code:
            raise RuntimeError(f"yt-dlp 下载失败，退出码 {code}")
        if final_path and final_path.exists():
            return final_path
        candidates = sorted(output_dir.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError("下载完成，但未找到输出文件")
        return candidates[0]

    def cancel(self) -> None:
        self.runner.cancel()
