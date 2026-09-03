from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models import TaskProgress, TranscodeConfig
from .paths import ffmpeg_path, ffprobe_path
from .processes import ProcessRunner, ProcessTimeout
from .transcode_options import (
    bitrate_for_target_size,
    clamp_audio_bitrate,
    estimate_size_mib,
    resolve_quality,
    resolve_scale,
    resolve_video_bitrate,
)
from .utils import sanitize_suffix, unique_path


@dataclass(slots=True)
class ProbeInfo:
    format_names: set[str]
    video_codec: str
    audio_codec: str
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bit_depth: int | None = None
    audio_bitrate: int | None = None
    video_bitrate: int | None = None
    format_bitrate: int | None = None
    file_size: int | None = None
    duration: float | None = None
    audio_channels: int | None = None
    audio_channel_layout: str = ""
    audio_sample_rate: int | None = None

    @property
    def is_mp4(self) -> bool:
        return bool(self.format_names & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})

    @property
    def video_compatible(self) -> bool:
        return self.video_codec == "h264"

    @property
    def audio_compatible(self) -> bool:
        return self.audio_codec in {"", "aac", "mp3", "ac3"}


class FFmpegService:
    HARDWARE_ENCODERS = {
        "nvidia": "h264_nvenc",
        "intel": "h264_qsv",
        "amd": "h264_amf",
    }
    HARDWARE_DECODERS = {
        "nvidia": "cuda",
        "intel": "qsv",
        "amd": "d3d11va",
    }
    HARDWARE_FILTERS = {
        "nvidia": "cuda",
        "intel": "qsv",
        "amd": "amf",
    }

    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self.runner = runner or ProcessRunner()
        self.selected_encoder = "libx264"
        self.capabilities: dict[str, bool] = {}

    @staticmethod
    def _fraction(value: str | None) -> float | None:
        if not value or value in {"0/0", "N/A"}:
            return None
        try:
            numerator, denominator = value.split("/", 1)
            return float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError):
            return None

    def probe(self, path: Path) -> ProbeInfo:
        args = [
            ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            (
                "format=format_name,duration,bit_rate:"
                "stream=codec_type,codec_name,width,height,bit_rate,avg_frame_rate,"
                "bits_per_raw_sample,bits_per_sample,channels,channel_layout,sample_rate"
            ),
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
        bit_depth = video.get("bits_per_raw_sample") or video.get("bits_per_sample")
        return ProbeInfo(
            format_names=set((format_data.get("format_name") or "").split(",")),
            video_codec=video.get("codec_name") or "",
            audio_codec=audio.get("codec_name") or "",
            width=video.get("width"),
            height=video.get("height"),
            fps=self._fraction(video.get("avg_frame_rate")),
            bit_depth=int(bit_depth) if bit_depth and str(bit_depth).isdigit() else None,
            audio_bitrate=int(audio["bit_rate"]) if audio.get("bit_rate") else None,
            video_bitrate=int(video["bit_rate"]) if video.get("bit_rate") else None,
            format_bitrate=int(format_data["bit_rate"]) if format_data.get("bit_rate") else None,
            file_size=path.stat().st_size if path.exists() else None,
            duration=float(format_data["duration"]) if format_data.get("duration") else None,
            audio_channels=int(audio["channels"]) if audio.get("channels") else None,
            audio_channel_layout=audio.get("channel_layout") or "",
            audio_sample_rate=int(audio["sample_rate"]) if audio.get("sample_rate") else None,
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
                "color=size=640x360:rate=30:duration=0.25",
                "-c:v",
                encoder,
                "-f",
                "null",
                "-",
            ]
            try:
                code, _ = self.runner.run(args, timeout=8)
            except ProcessTimeout:
                code = -1
                if on_log:
                    on_log(f"{vendor.upper()} 硬件编码探测超时，已跳过 ({encoder})")
            availability[vendor] = code == 0
            if on_log:
                on_log(f"{vendor.upper()} 硬件编码：{'可用' if code == 0 else '不可用'} ({encoder})")

        try:
            _, hwaccels = self.runner.run(
                [ffmpeg_path(), "-hide_banner", "-hwaccels"], capture=True, timeout=5
            )
        except ProcessTimeout:
            hwaccels = ""
            if on_log:
                on_log("硬件解码能力探测超时，已跳过")
        methods = {line.strip() for line in hwaccels.splitlines()}
        for method in ("cuda", "qsv", "d3d11va", "d3d12va", "dxva2"):
            availability[f"decode_{method}"] = method in methods

        try:
            _, filters = self.runner.run(
                [ffmpeg_path(), "-hide_banner", "-filters"], capture=True, timeout=5
            )
        except ProcessTimeout:
            filters = ""
            if on_log:
                on_log("硬件滤镜能力探测超时，已跳过")
        availability["filter_cuda"] = "scale_cuda" in filters
        availability["filter_qsv"] = "scale_qsv" in filters
        availability["filter_amf"] = "vpp_amf" in filters
        self.capabilities = availability
        return availability

    def select_encoder(self, config: TranscodeConfig) -> str:
        self.selected_encoder = self.HARDWARE_ENCODERS.get(config.video_encoder, "libx264")
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
    def _has_image_changes(config: TranscodeConfig) -> bool:
        return any(
            (
                config.scale != "源尺寸",
                config.portrait and config.scale != "源尺寸",
                config.rotation != "0",
                config.mirror,
                config.force_display_aspect,
            )
        )

    @staticmethod
    def _audio_plan(info: ProbeInfo, config: TranscodeConfig) -> tuple[str, str]:
        if not info.audio_codec:
            return "none", ""
        if config.audio_convert:
            if config.audio_codec == "none":
                return "none", ""
            if config.audio_codec == "copy":
                return ("copy", info.audio_codec) if info.audio_compatible else ("encode", "aac")
            return "encode", config.audio_codec
        return ("copy", info.audio_codec) if info.audio_compatible else ("encode", "aac")

    @classmethod
    def decide_config_action(cls, info: ProbeInfo, config: TranscodeConfig) -> str:
        video_encode = not info.video_compatible or cls._has_image_changes(config)
        audio_mode, _ = cls._audio_plan(info, config)
        audio_change = audio_mode == "encode" or (
            config.audio_convert and config.audio_codec == "none"
        )
        if not video_encode and not audio_change and info.is_mp4:
            return "none"
        if not video_encode and not audio_change:
            return "remux"
        if video_encode and audio_change:
            return "both"
        return "video" if video_encode else "audio"

    @staticmethod
    def _resolved_scale(info: ProbeInfo, config: TranscodeConfig):
        return resolve_scale(
            config.scale,
            info.width,
            info.height,
            portrait=config.portrait,
            no_upscale=config.no_upscale,
        )

    @classmethod
    def resolved_video_bitrate(cls, info: ProbeInfo, config: TranscodeConfig) -> int:
        scale = cls._resolved_scale(info, config)
        audio_rate = clamp_audio_bitrate(config.audio_codec, config.audio_bitrate_kbps) or 0
        if config.size_locked and config.target_size_mib:
            return bitrate_for_target_size(info.duration, config.target_size_mib, audio_rate)
        return resolve_video_bitrate(
            config.video_bitrate,
            scale.width,
            scale.height,
            info.fps,
        )

    @classmethod
    def estimated_size_mib(cls, info: ProbeInfo, config: TranscodeConfig) -> float | None:
        if config.rate_mode == "cq":
            return None
        audio_rate = clamp_audio_bitrate(config.audio_codec, config.audio_bitrate_kbps) or 0
        return estimate_size_mib(
            info.duration,
            cls.resolved_video_bitrate(info, config),
            audio_rate,
        )

    @classmethod
    def _video_rate_args(
        cls,
        encoder: str,
        config: TranscodeConfig,
        info: ProbeInfo,
    ) -> list[str]:
        quality = resolve_quality(config.quality)
        maxrate: int | None = None
        if str(config.maximum_bitrate).strip().lower() != "auto":
            maxrate = resolve_video_bitrate(
                config.maximum_bitrate,
                cls._resolved_scale(info, config).width,
                cls._resolved_scale(info, config).height,
                info.fps,
            )

        if config.rate_mode == "cq":
            limits = ["-maxrate", f"{maxrate}k", "-bufsize", f"{maxrate * 2}k"] if maxrate else []
            if encoder == "libx264":
                args = ["-crf", str(quality)]
            elif encoder == "h264_nvenc":
                args = ["-rc", "vbr", "-cq", str(quality), "-b:v", "0"]
            elif encoder == "h264_qsv":
                args = ["-global_quality", str(quality)]
            else:
                args = ["-rc", "cqp", "-qp_i", str(quality), "-qp_p", str(quality), "-qp_b", str(quality)]
            return [*args, *limits, *cls._quality_preset_args(encoder, config)]

        bitrate = cls.resolved_video_bitrate(info, config)
        if config.rate_mode == "cbr":
            ceiling = max(maxrate or bitrate, bitrate)
            common = [
                "-b:v",
                f"{bitrate}k",
                "-minrate",
                f"{bitrate}k",
                "-maxrate",
                f"{ceiling}k",
                "-bufsize",
                f"{ceiling * 2}k",
            ]
            if encoder == "h264_nvenc":
                common.extend(["-rc", "cbr"])
            elif encoder == "h264_amf":
                common.extend(["-rc", "cbr"])
        else:
            common = ["-b:v", f"{bitrate}k"]
            if maxrate:
                maxrate = max(maxrate, bitrate)
                common.extend(["-maxrate", f"{maxrate}k", "-bufsize", f"{maxrate * 2}k"])
            if encoder == "h264_nvenc":
                common.extend(["-rc", "vbr"])
            elif encoder == "h264_amf":
                common.extend(["-rc", "vbr_peak"])
        return [*common, *cls._quality_preset_args(encoder, config)]

    @staticmethod
    def _quality_preset_args(encoder: str, config: TranscodeConfig) -> list[str]:
        if config.highest_quality:
            if encoder == "libx264":
                return ["-preset", "veryslow"]
            if encoder == "h264_nvenc":
                return ["-preset", "p7", "-tune", "hq"]
            if encoder == "h264_qsv":
                return ["-preset", "veryslow"]
            return ["-quality", "quality"]
        if encoder == "libx264":
            return ["-preset", "medium"]
        if encoder == "h264_nvenc":
            return ["-preset", "p5"]
        return []

    @classmethod
    def _software_filters(cls, info: ProbeInfo, config: TranscodeConfig) -> list[str]:
        decision = cls._resolved_scale(info, config)
        filters: list[str] = []
        flags = config.scale_algorithm
        if decision.kind == "fixed":
            filters.extend(
                [
                    (
                        f"scale={decision.width}:{decision.height}:"
                        f"force_original_aspect_ratio=decrease:flags={flags}"
                    ),
                    (
                        f"pad={decision.width}:{decision.height}:"
                        "(ow-iw)/2:(oh-ih)/2:color=black"
                    ),
                ]
            )
        elif decision.kind != "source":
            filters.append(f"scale={decision.width}:{decision.height}:flags={flags}")
        if config.rotation == "90":
            filters.append("transpose=1")
        elif config.rotation == "-90":
            filters.append("transpose=2")
        elif config.rotation == "180":
            filters.extend(["transpose=1", "transpose=1"])
        if config.mirror:
            filters.append("hflip")
        if config.force_display_aspect:
            filters.extend(["setsar=1", f"setdar={decision.width}/{decision.height}"])
        return filters

    def _hardware_video_input(
        self,
        info: ProbeInfo,
        config: TranscodeConfig,
        encoder: str,
        on_log: Callable[[str], None] | None = None,
    ) -> tuple[list[str], list[str]]:
        software = self._software_filters(info, config)
        vendor = config.video_encoder
        if vendor == "cpu":
            return [], software
        decode = config.hardware_decode
        if decode == "auto":
            decode = self.HARDWARE_DECODERS[vendor]
        filter_backend = config.hardware_filter
        if filter_backend == "auto":
            filter_backend = self.HARDWARE_FILTERS[vendor]

        decision = self._resolved_scale(info, config)
        simple_scale = (
            decision.kind in {"ratio", "auto"}
            and config.rotation == "0"
            and not config.mirror
            and not config.force_display_aspect
        )
        matching = {
            "nvidia": ("cuda", "cuda", "h264_nvenc", "scale_cuda"),
            "intel": ("qsv", "qsv", "h264_qsv", "scale_qsv"),
        }.get(vendor)
        if (
            simple_scale
            and matching
            and decode == matching[0]
            and filter_backend == matching[1]
            and encoder == matching[2]
            and self.capabilities.get(f"decode_{decode}", True)
            and self.capabilities.get(f"filter_{filter_backend}", True)
        ):
            return (
                ["-hwaccel", decode, "-hwaccel_output_format", decode],
                [f"{matching[3]}={decision.width}:{decision.height}"],
            )

        if config.hardware_filter not in {"auto", "none"} and software and on_log:
            on_log("当前图像操作不适合所选硬件滤镜，已改用软件滤镜")
        if filter_backend == "none" or software:
            return [], software
        if decode not in {"none", "auto"}:
            output_format = "cuda" if decode == "cuda" else "qsv" if decode == "qsv" else None
            args = ["-hwaccel", decode]
            if output_format:
                args.extend(["-hwaccel_output_format", output_format])
            return args, []
        return [], software

    @staticmethod
    def _audio_args(info: ProbeInfo, config: TranscodeConfig) -> tuple[list[str], str]:
        mode, codec = FFmpegService._audio_plan(info, config)
        if mode == "none":
            return ["-an"], ""
        if mode == "copy":
            return ["-c:a", "copy"], codec

        ffmpeg_codec = {"aac": "aac", "mp3": "libmp3lame", "ac3": "ac3"}[codec]
        args = ["-c:a", ffmpeg_codec]
        bitrate = clamp_audio_bitrate(codec, config.audio_bitrate_kbps)
        if bitrate:
            args.extend(["-b:a", f"{bitrate}k"])
        if config.audio_sample_rate:
            args.extend(["-ar", str(config.audio_sample_rate)])
        if config.audio_channels == "mono":
            args.extend(["-ac", "1"])
        elif config.audio_channels == "stereo":
            args.extend(["-ac", "2"])
            if (info.audio_channels or 0) > 2:
                layout = info.audio_channel_layout
                if layout == "7.1":
                    pan = (
                        "pan=stereo|FL=0.6*FL+0.5*FC+0.3*BL+0.3*SL+0.2*LFE|"
                        "FR=0.6*FR+0.5*FC+0.3*BR+0.3*SR+0.2*LFE"
                    )
                elif layout == "6.1":
                    pan = (
                        "pan=stereo|FL=0.6*FL+0.5*FC+0.3*BC+0.3*SL+0.2*LFE|"
                        "FR=0.6*FR+0.5*FC+0.3*BC+0.3*SR+0.2*LFE"
                    )
                else:
                    pan = (
                        "pan=stereo|FL=0.707*FL+0.707*FC+0.5*BL+0.5*SL|"
                        "FR=0.707*FR+0.707*FC+0.5*BR+0.5*SR"
                    )
                args.extend(["-af", pan])
        elif config.audio_channels == "5.1":
            args.extend(["-ac", "6"])
        return args, codec

    @staticmethod
    def output_suffix(config: TranscodeConfig, video_codec: str, audio_codec: str) -> str:
        if config.suffix_mode == "none":
            return ""
        if config.suffix_mode == "custom":
            custom = sanitize_suffix(config.custom_suffix)
            if custom:
                return custom
        video = (video_codec or "video").upper().replace(".", "")
        audio = (audio_codec or "NOAUDIO").upper().replace(".", "")
        return sanitize_suffix(f"{video}_{audio}")

    def _build_args(
        self,
        source: Path,
        target: Path | None,
        action: str,
        encoder: str,
        config: TranscodeConfig,
        info: ProbeInfo,
        *,
        pass_number: int | None = None,
        passlog: Path | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> tuple[list[str], str]:
        video_encode = action in {"video", "both"}
        if video_encode:
            hardware_input, filters = self._hardware_video_input(info, config, encoder, on_log)
        else:
            hardware_input, filters = [], []
        args = [str(ffmpeg_path()), "-hide_banner", "-y", *hardware_input, "-i", str(source)]
        args.extend(["-map", "0:v:0?"])
        if pass_number != 1:
            args.extend(["-map", "0:a:0?"])

        if video_encode:
            args.extend(["-c:v", encoder])
            if filters:
                args.extend(["-vf", ",".join(filters)])
            args.extend(self._video_rate_args(encoder, config, info))
        else:
            args.extend(["-c:v", "copy"])

        expected_audio = info.audio_codec
        if pass_number == 1:
            args.append("-an")
        else:
            audio_args, expected_audio = self._audio_args(info, config)
            args.extend(audio_args)

        if pass_number is not None and passlog:
            args.extend(["-pass", str(pass_number), "-passlogfile", str(passlog)])
        args.extend(["-progress", "pipe:1", "-nostats"])
        if pass_number == 1:
            args.extend(["-f", "null", "NUL" if os.name == "nt" else "/dev/null"])
        else:
            args.extend(["-movflags", "+faststart", str(target)])
        return args, expected_audio

    @staticmethod
    def _clean_passlogs(prefix: Path) -> None:
        for path in prefix.parent.glob(f"{prefix.name}*"):
            path.unlink(missing_ok=True)

    def convert(
        self,
        source: Path,
        config: TranscodeConfig,
        on_progress: Callable[[TaskProgress], None],
        on_log: Callable[[str], None],
    ) -> Path:
        info = self.probe(source)
        action = self.decide_config_action(info, config)
        if action == "none":
            on_log("文件已经满足当前 H.264 MP4、图像和音频设置，无需处理")
            return source
        encoder = self.select_encoder(config)
        video_encode = action in {"video", "both"}
        if not video_encode:
            encoder = "libx264"
        _, expected_audio = self._audio_args(info, config)
        expected_video = "h264" if video_encode else info.video_codec
        suffix = self.output_suffix(config, expected_video, expected_audio)
        final = unique_path(source.with_name(f"{source.stem}{suffix}.mp4"))
        temp = final.with_name(f"{final.stem}.transcoding.tmp.mp4")
        passlog = final.with_name(f".{final.stem}.passlog")
        two_pass = bool(
            config.two_pass
            and config.video_encoder == "cpu"
            and config.rate_mode in {"vbr", "cbr"}
            and video_encode
        )
        duration_us = (info.duration or 0) * 1_000_000

        if (
            info.audio_codec
            and not info.audio_compatible
            and (not config.audio_convert or config.audio_codec == "copy")
        ):
            on_log(f"源音频 {info.audio_codec} 不适合 MP4，已自动转换为 AAC")
        if config.rate_mode != "cq" and video_encode:
            bitrate = self.resolved_video_bitrate(info, config)
            size = self.estimated_size_mib(info, config)
            on_log(
                f"视频码率：{bitrate} kbps"
                + (f"，预计文件大小：{size:.1f} MiB" if size is not None else "")
            )

        def run_once(pass_number: int | None) -> tuple[int, str]:
            last_lines: list[str] = []
            if pass_number == 1:
                start, span = 0.0, 50.0
            elif pass_number == 2:
                start, span = 50.0, 50.0
            else:
                start, span = 0.0, 100.0

            def handle(line: str) -> None:
                last_lines.append(line)
                if len(last_lines) > 40:
                    last_lines.pop(0)
                if (line.startswith("out_time_us=") or line.startswith("out_time_ms=")) and duration_us:
                    try:
                        raw = min(100.0, float(line.split("=", 1)[1]) / duration_us * 100)
                        on_progress(
                            TaskProgress(
                                stage="二次编码" if pass_number else "转码",
                                stage_percent=start + raw / 100 * span,
                            )
                        )
                    except ValueError:
                        pass
                elif not line.startswith("progress="):
                    on_log(line)

            args, _ = self._build_args(
                source,
                temp,
                action,
                encoder,
                config,
                info,
                pass_number=pass_number,
                passlog=passlog,
                on_log=on_log,
            )
            code, _ = self.runner.run(args, on_line=handle)
            return code, "\n".join(last_lines)

        on_log(f"处理方式：{action}，编码器：{encoder}")
        try:
            if two_pass:
                on_log("开始第一遍分析编码")
                code, diagnostic = run_once(1)
                if code:
                    raise RuntimeError(f"FFmpeg 第一遍编码失败：{diagnostic}")
                on_log("开始第二遍正式编码")
                code, diagnostic = run_once(2)
            else:
                code, diagnostic = run_once(None)
            if code:
                if encoder != "libx264" and video_encode:
                    raise HardwareEncodingError(encoder, diagnostic)
                raise RuntimeError(f"FFmpeg 处理失败：{diagnostic}")

            verified = self.probe(temp)
            audio_valid = (
                not expected_audio
                or verified.audio_codec == expected_audio
                or expected_audio == "mp3" and verified.audio_codec == "mp3"
            )
            if not (verified.is_mp4 and verified.video_codec == expected_video and audio_valid):
                raise RuntimeError("输出文件验证失败，源文件已保留")
            os.replace(temp, final)
            if not config.keep_source and source.resolve() != final.resolve():
                source.unlink(missing_ok=True)
            return final
        finally:
            temp.unlink(missing_ok=True)
            self._clean_passlogs(passlog)

    def cancel(self) -> None:
        self.runner.cancel()


class HardwareEncodingError(RuntimeError):
    def __init__(self, encoder: str, diagnostic: str) -> None:
        super().__init__(f"{encoder} 硬件转码失败：{diagnostic}")
        self.encoder = encoder
