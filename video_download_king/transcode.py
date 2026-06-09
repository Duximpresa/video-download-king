from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models import TaskProgress, TranscodeConfig
from .paths import ffmpeg_path, ffprobe_path
from .processes import ProcessRunner
from .utils import sanitize_suffix, unique_path


@dataclass(slots=True)
class ProbeInfo:
    format_names: set[str]
    video_codec: str
    audio_codec: str
    width: int | None = None
    height: int | None = None
    audio_bitrate: int | None = None
    video_bitrate: int | None = None
    format_bitrate: int | None = None
    file_size: int | None = None
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


@dataclass(slots=True, frozen=True)
class VideoRateDecision:
    strategy: str
    source_codec: str
    source_bitrate_kbps: int | None
    multiplier: float | None = None
    target_bitrate_kbps: int | None = None
    quality: int | None = None
    maxrate_kbps: int | None = None
    bufsize_kbps: int | None = None


class FFmpegService:
    HARDWARE_ENCODERS = {
        "nvidia": "h264_nvenc",
        "intel": "h264_qsv",
        "amd": "h264_amf",
    }

    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self.runner = runner or ProcessRunner()
        self.selected_encoder = "libx264"

    def probe(self, path: Path) -> ProbeInfo:
        args = [
            ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration,bit_rate:stream=codec_type,codec_name,width,height,bit_rate",
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
            video_bitrate=int(video["bit_rate"]) if video.get("bit_rate") else None,
            format_bitrate=int(format_data["bit_rate"]) if format_data.get("bit_rate") else None,
            file_size=path.stat().st_size if path.exists() else None,
            duration=float(format_data["duration"]) if format_data.get("duration") else None,
        )

    def detect_encoders(self, on_log: Callable[[str], None] | None = None) -> dict[str, bool]:
        availability: dict[str, bool] = {}
        for vendor, encoder in self.HARDWARE_ENCODERS.items():
            args = [
                ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=640x360:rate=30:duration=0.5",
                "-c:v",
                encoder,
                "-f",
                "null",
                "-",
            ]
            code, _ = self.runner.run(args)
            availability[vendor] = code == 0
            if on_log:
                on_log(f"{vendor.upper()} 硬件编码：{'可用' if code == 0 else '不可用'} ({encoder})")
        return availability

    def select_encoder(self, config: TranscodeConfig) -> str:
        if config.processor == "cpu":
            self.selected_encoder = "libx264"
        else:
            self.selected_encoder = self.HARDWARE_ENCODERS.get(config.hardware_vendor, "libx264")
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
    def _fallback_video_bitrate(height: int | None) -> int:
        if not height:
            return 800
        if height >= 2160:
            return 20000
        if height >= 1440:
            return 10000
        if height >= 1080:
            return 5000
        if height >= 720:
            return 2500
        if height >= 480:
            return 1200
        return 800

    @staticmethod
    def source_video_bitrate(info: ProbeInfo, hinted_kbps: int | None = None) -> int | None:
        if info.video_bitrate and info.video_bitrate > 0:
            return max(100, round(info.video_bitrate / 1000))
        if info.format_bitrate and info.format_bitrate > 0:
            estimated = info.format_bitrate - (info.audio_bitrate or 0)
            if estimated > 0:
                return max(100, round(estimated / 1000))
        if info.file_size and info.duration and info.duration > 0:
            total = info.file_size * 8 / info.duration
            estimated = total - (info.audio_bitrate or 0)
            if estimated > 0:
                return max(100, round(estimated / 1000))
        if hinted_kbps and hinted_kbps > 0:
            return max(100, round(hinted_kbps))
        return None

    @staticmethod
    def normalize_video_codec(codec: str) -> str:
        value = (codec or "").strip().lower()
        aliases = {
            "avc": "h264",
            "avc1": "h264",
            "h.264": "h264",
            "h265": "hevc",
            "h.265": "hevc",
            "hev1": "hevc",
            "hvc1": "hevc",
            "av01": "av1",
            "mpeg2video": "mpeg2",
            "mpeg-2": "mpeg2",
            "mpeg-4": "mpeg4",
        }
        if value.startswith("vp09"):
            return "vp9"
        if value.startswith("vp08"):
            return "vp8"
        return aliases.get(value, value)

    @staticmethod
    def automatic_rate_decision(info: ProbeInfo, config: TranscodeConfig) -> VideoRateDecision:
        codec = FFmpegService.normalize_video_codec(info.video_codec or config.source_video_codec)
        source = FFmpegService.source_video_bitrate(info, config.source_video_bitrate_kbps)
        gpu = config.processor == "gpu"
        multipliers = {
            "h264": (1.0, 1.0),
            "vp8": (1.3, 1.3),
            "vp9": (1.8, 2.0),
            "hevc": (2.0, 2.2),
            "av1": (2.0, 2.2),
            "mpeg4": (1.0, 1.0),
            "mpeg2": (1.0, 1.0),
        }
        if codec in multipliers:
            multiplier = multipliers[codec][1 if gpu else 0]
            target = FFmpegService._fallback_video_bitrate(info.height)
            if source:
                target = max(100, min(round(source * multiplier), round(source * 2.2)))
            return VideoRateDecision(
                strategy="bitrate",
                source_codec=codec,
                source_bitrate_kbps=source,
                multiplier=multiplier,
                target_bitrate_kbps=target,
            )

        volume_base = source or FFmpegService._fallback_video_bitrate(info.height)
        return VideoRateDecision(
            strategy="constrained_quality",
            source_codec=codec or "unknown",
            source_bitrate_kbps=source,
            quality=23,
            maxrate_kbps=max(100, round(volume_base * 2.0)),
            bufsize_kbps=max(200, round(volume_base * 4.0)),
        )

    @staticmethod
    def auto_video_bitrate(info: ProbeInfo, hinted_kbps: int | None = None) -> int:
        source = FFmpegService.source_video_bitrate(info, hinted_kbps)
        return source or FFmpegService._fallback_video_bitrate(info.height)

    @staticmethod
    def _auto_audio_bitrate(info: ProbeInfo) -> int:
        source = (info.audio_bitrate or 192000) // 1000
        return max(96, min(256, source))

    @staticmethod
    def _video_quality_args(encoder: str, config: TranscodeConfig, info: ProbeInfo) -> list[str]:
        if config.rate_mode == "bitrate" and config.video_bitrate_kbps:
            return ["-b:v", f"{config.video_bitrate_kbps}k"]
        if config.rate_mode == "auto":
            decision = FFmpegService.automatic_rate_decision(info, config)
            if decision.strategy == "bitrate":
                return ["-b:v", f"{decision.target_bitrate_kbps}k"]
            quality = str(decision.quality or 23)
            limits = [
                "-maxrate",
                f"{decision.maxrate_kbps}k",
                "-bufsize",
                f"{decision.bufsize_kbps}k",
            ]
            if encoder == "libx264":
                return ["-crf", quality, "-preset", "medium", *limits]
            if encoder == "h264_nvenc":
                return ["-rc", "vbr", "-cq", quality, "-b:v", "0", "-preset", "p5", *limits]
            if encoder == "h264_qsv":
                return ["-global_quality", quality, *limits]
            return ["-qp_i", quality, "-qp_p", quality, *limits]
        quality = str(max(0, min(51, config.quality)))
        if encoder == "libx264":
            return ["-crf", quality, "-preset", "medium"]
        if encoder == "h264_nvenc":
            return ["-cq", quality, "-preset", "p5"]
        if encoder == "h264_qsv":
            return ["-global_quality", quality]
        return ["-qp_i", quality, "-qp_p", quality]

    @staticmethod
    def output_suffix(config: TranscodeConfig, video_codec: str, audio_codec: str) -> str:
        if config.suffix_mode == "none":
            return ""
        if config.suffix_mode == "custom":
            custom = sanitize_suffix(config.custom_suffix)
            if custom:
                return custom
        video = (video_codec or "video").upper().replace(".", "")
        audio = (audio_codec or "audio").upper().replace(".", "")
        return sanitize_suffix(f"{video}_{audio}")

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
        expected_video = "h264" if action in {"video", "both"} else info.video_codec
        expected_audio = "aac" if action in {"audio", "both"} else info.audio_codec
        suffix = self.output_suffix(config, expected_video, expected_audio)
        final = unique_path(source.with_name(f"{source.stem}{suffix}.mp4"))
        temp = final.with_name(f"{final.stem}.transcoding.tmp.mp4")
        encoder = self.select_encoder(config)
        duration_us = (info.duration or 0) * 1_000_000
        if action in {"video", "both"} and config.rate_mode == "auto":
            decision = self.automatic_rate_decision(info, config)
            source_rate = (
                f"{decision.source_bitrate_kbps} kbps"
                if decision.source_bitrate_kbps
                else "unknown"
            )
            if decision.strategy == "bitrate":
                on_log(
                    "自动码率："
                    f"源编码={decision.source_codec}，源码率={source_rate}，"
                    f"补偿系数={decision.multiplier:.1f}x，目标码率={decision.target_bitrate_kbps} kbps，"
                    f"处理器={config.processor.upper()}"
                )
            else:
                on_log(
                    "自动质量保护："
                    f"源编码={decision.source_codec}，源码率={source_rate}，"
                    f"质量值={decision.quality}，maxrate={decision.maxrate_kbps} kbps，"
                    f"bufsize={decision.bufsize_kbps} kbps，处理器={config.processor.upper()}"
                )

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
        if code:
            temp.unlink(missing_ok=True)
            if encoder != "libx264" and action in {"video", "both"}:
                raise HardwareEncodingError(encoder, diagnostic)
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


class HardwareEncodingError(RuntimeError):
    def __init__(self, encoder: str, diagnostic: str) -> None:
        super().__init__(f"{encoder} 硬件转码失败：{diagnostic}")
        self.encoder = encoder
