from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models import TaskProgress, TranscodeConfig
from .paths import ffmpeg_path, ffprobe_path
from .processes import ProcessRunner
from .utils import unique_path


@dataclass(slots=True)
class ProbeInfo:
    format_names: set[str]
    video_codec: str
    audio_codec: str
    width: int | None = None
    height: int | None = None
    audio_bitrate: int | None = None
    duration: float | None = None

    @property
    def is_mp4(self) -> bool:
        return bool(self.format_names & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})

    @property
    def video_compatible(self) -> bool:
        return self.video_codec == "h264"

    @property
    def audio_compatible(self) -> bool:
        return self.audio_codec == "aac" or not self.audio_codec


class FFmpegService:
    HARDWARE_ENCODERS = ("h264_nvenc", "h264_qsv", "h264_amf")

    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self.runner = runner or ProcessRunner()
        self.selected_encoder = "libx264"

    def probe(self, path: Path) -> ProbeInfo:
        args = [
            ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration:stream=codec_type,codec_name,width,height,bit_rate",
            "-of",
            "json",
            path,
        ]
        code, output = self.runner.run(args, capture=True)
        if code:
            raise RuntimeError(f"FFprobe 检测失败：{output}")
        data = json.loads(output)
        video: dict = {}
        audio: dict = {}
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and not video:
                video = stream
            elif stream.get("codec_type") == "audio" and not audio:
                audio = stream
        format_data = data.get("format", {})
        return ProbeInfo(
            format_names=set((format_data.get("format_name") or "").split(",")),
            video_codec=video.get("codec_name") or "",
            audio_codec=audio.get("codec_name") or "",
            width=video.get("width"),
            height=video.get("height"),
            audio_bitrate=int(audio["bit_rate"]) if audio.get("bit_rate") else None,
            duration=float(format_data["duration"]) if format_data.get("duration") else None,
        )

    def detect_encoder(self, on_log: Callable[[str], None] | None = None) -> str:
        for encoder in self.HARDWARE_ENCODERS:
            args = [
                ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=128x128:rate=1:duration=0.2",
                "-c:v",
                encoder,
                "-f",
                "null",
                "-",
            ]
            code, _ = self.runner.run(args)
            if code == 0:
                self.selected_encoder = encoder
                if on_log:
                    on_log(f"硬件编码器可用：{encoder}")
                return encoder
        self.selected_encoder = "libx264"
        if on_log:
            on_log("未检测到可用硬件 H.264 编码器，将使用 CPU (libx264)")
        return self.selected_encoder

    @staticmethod
    def decide_action(info: ProbeInfo) -> str:
        if info.is_mp4 and info.video_compatible and info.audio_compatible:
            return "none"
        if info.video_compatible and info.audio_compatible:
            return "remux"
        if info.video_compatible:
            return "audio"
        if info.audio_compatible:
            return "video"
        return "both"

    @staticmethod
    def _auto_video_bitrate(height: int | None) -> int:
        if not height:
            return 5000
        if height >= 2160:
            return 35000
        if height >= 1440:
            return 16000
        if height >= 1080:
            return 8000
        if height >= 720:
            return 5000
        return 2500

    @staticmethod
    def _auto_audio_bitrate(info: ProbeInfo) -> int:
        source = (info.audio_bitrate or 192000) // 1000
        return max(96, min(256, source))

    @staticmethod
    def _video_quality_args(encoder: str, config: TranscodeConfig, info: ProbeInfo) -> list[str]:
        if config.rate_mode == "bitrate" and config.video_bitrate_kbps:
            return ["-b:v", f"{config.video_bitrate_kbps}k"]
        if config.rate_mode == "auto":
            return ["-b:v", f"{FFmpegService._auto_video_bitrate(info.height)}k"]
        quality = str(max(0, min(51, config.quality)))
        if encoder == "libx264":
            return ["-crf", quality, "-preset", "medium"]
        if encoder == "h264_nvenc":
            return ["-cq", quality, "-preset", "p5"]
        if encoder == "h264_qsv":
            return ["-global_quality", quality]
        return ["-qp_i", quality, "-qp_p", quality]

    def _build_args(
        self,
        source: Path,
        target: Path,
        action: str,
        encoder: str,
        config: TranscodeConfig,
        info: ProbeInfo,
    ) -> list[str]:
        args = [str(ffmpeg_path()), "-hide_banner", "-y", "-i", str(source), "-map", "0:v:0?", "-map", "0:a:0?"]
        if action in {"none", "remux"}:
            args.extend(["-c", "copy"])
        else:
            if action == "audio":
                args.extend(["-c:v", "copy"])
            else:
                args.extend(["-c:v", encoder, *self._video_quality_args(encoder, config, info)])
            if action == "video":
                args.extend(["-c:a", "copy"])
            else:
                audio_rate = config.audio_bitrate_kbps or self._auto_audio_bitrate(info)
                args.extend(["-c:a", "aac", "-b:a", f"{audio_rate}k"])
        args.extend(["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(target)])
        return args

    def convert(
        self,
        source: Path,
        config: TranscodeConfig,
        on_progress: Callable[[TaskProgress], None],
        on_log: Callable[[str], None],
    ) -> Path:
        info = self.probe(source)
        action = self.decide_action(info)
        if action == "none":
            on_log("文件已经是 H.264 + AAC MP4，无需处理")
            return source
        final = unique_path(source.with_suffix(".mp4"))
        temp = final.with_name(f"{final.stem}.transcoding.tmp.mp4")
        encoder = self.selected_encoder
        duration_us = (info.duration or 0) * 1_000_000

        def run_once(selected: str) -> tuple[int, str]:
            last_lines: list[str] = []

            def handle(line: str) -> None:
                last_lines.append(line)
                if len(last_lines) > 30:
                    last_lines.pop(0)
                if (line.startswith("out_time_us=") or line.startswith("out_time_ms=")) and duration_us:
                    try:
                        percent = min(100.0, float(line.split("=", 1)[1]) / duration_us * 100)
                        on_progress(TaskProgress(stage="转码", percent=percent))
                    except ValueError:
                        pass
                elif line.startswith("progress="):
                    return
                else:
                    on_log(line)

            code, _ = self.runner.run(
                self._build_args(source, temp, action, selected, config, info),
                on_line=handle,
            )
            return code, "\n".join(last_lines)

        on_log(f"处理方式：{action}，编码器：{encoder}")
        code, diagnostic = run_once(encoder)
        if code and encoder != "libx264" and action in {"video", "both"}:
            on_log("硬件转码失败，自动回退 CPU (libx264)")
            temp.unlink(missing_ok=True)
            code, diagnostic = run_once("libx264")
        if code:
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg 处理失败：{diagnostic}")
        verified = self.probe(temp)
        if not (verified.is_mp4 and verified.video_compatible and verified.audio_compatible):
            temp.unlink(missing_ok=True)
            raise RuntimeError("输出文件验证失败，源文件已保留")
        os.replace(temp, final)
        if not config.keep_source and source.resolve() != final.resolve():
            source.unlink(missing_ok=True)
        return final

    def cancel(self) -> None:
        self.runner.cancel()
