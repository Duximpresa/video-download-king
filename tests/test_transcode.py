from pathlib import Path

import pytest

from video_download_king.models import TranscodeConfig
from video_download_king.transcode import FFmpegService, ProbeInfo
from video_download_king.transcode_options import (
    bitrate_for_target_size,
    estimate_size_mib,
    portrait_expression,
    resolve_scale,
    shutter_auto_bitrate,
)


def probe(container: str, video: str, audio: str, **kwargs) -> ProbeInfo:
    values = {
        "width": 1920,
        "height": 1080,
        "fps": 25,
        "duration": 100,
        "audio_channels": 2,
        "audio_channel_layout": "stereo",
    }
    values.update(kwargs)
    return ProbeInfo(set(container.split(",")), video, audio, **values)


def test_transcode_decisions() -> None:
    assert FFmpegService.decide_action(probe("mov,mp4", "h264", "aac")) == "none"
    assert FFmpegService.decide_action(probe("matroska", "h264", "aac")) == "remux"
    assert FFmpegService.decide_action(probe("matroska", "h264", "opus")) == "audio"
    assert FFmpegService.decide_action(probe("matroska", "vp9", "aac")) == "video"
    assert FFmpegService.decide_action(probe("matroska", "vp9", "opus")) == "both"

    info = probe("mov,mp4", "h264", "aac")
    assert FFmpegService.decide_config_action(info, TranscodeConfig()) == "none"
    assert (
        FFmpegService.decide_config_action(
            info,
            TranscodeConfig(scale="1280x720"),
        )
        == "video"
    )
    assert (
        FFmpegService.decide_config_action(
            info,
            TranscodeConfig(audio_convert=True, audio_codec="none"),
        )
        == "audio"
    )


def test_scale_presets_custom_values_and_portrait() -> None:
    assert resolve_scale("源尺寸", 1920, 1080) .width == 1920
    ratio = resolve_scale("1:2", 1920, 1080)
    assert (ratio.width, ratio.height, ratio.kind) == (960, 540, "ratio")
    auto_height = resolve_scale("auto:720", 1920, 1080)
    assert (auto_height.width, auto_height.height) == (1280, 720)
    custom = resolve_scale("1001x777", 1920, 1080)
    assert (custom.width, custom.height) == (1002, 778)
    assert portrait_expression("1920x1080", True) == "1080x1920"
    assert portrait_expression("1080x1920", True) == "1080x1920"
    assert portrait_expression("auto:720", True) == "720:auto"
    assert portrait_expression("720:auto", False) == "auto:720"
    portrait = resolve_scale("1080x1920", 1920, 1080, portrait=True)
    assert (portrait.width, portrait.height) == (1080, 1920)
    no_upscale = resolve_scale("4096x2160", 1920, 1080, no_upscale=True)
    assert (no_upscale.width, no_upscale.height, no_upscale.kind) == (1920, 1080, "source")
    with pytest.raises(ValueError):
        resolve_scale("auto:auto", 1920, 1080)


def test_shutter_h264_bitrate_tiers_and_target_size() -> None:
    auto = shutter_auto_bitrate(1920, 1080, 25, "auto")
    assert auto == 5000
    assert shutter_auto_bitrate(1920, 1080, 25, "好的") == 10000
    assert shutter_auto_bitrate(1920, 1080, 25, "最好") == 20000
    assert shutter_auto_bitrate(1280, 720, None, "auto") == 2222
    size = estimate_size_mib(100, 5000, 256)
    assert size == pytest.approx(64.16, abs=0.01)
    assert bitrate_for_target_size(100, size, 256) == 5000


def test_cpu_vbr_cbr_and_cq_args() -> None:
    info = probe("matroska", "vp9", "opus")
    vbr = TranscodeConfig(rate_mode="vbr", video_bitrate="auto")
    assert FFmpegService._video_rate_args("libx264", vbr, info) == [
        "-b:v",
        "5000k",
        "-preset",
        "medium",
    ]

    cbr = TranscodeConfig(
        rate_mode="cbr",
        video_bitrate="4000",
        maximum_bitrate="5000",
    )
    assert FFmpegService._video_rate_args("libx264", cbr, info) == [
        "-b:v",
        "4000k",
        "-minrate",
        "4000k",
        "-maxrate",
        "5000k",
        "-bufsize",
        "10000k",
        "-preset",
        "medium",
    ]

    cq = TranscodeConfig(
        rate_mode="cq",
        quality=21,
        maximum_bitrate="6000",
        highest_quality=True,
    )
    assert FFmpegService._video_rate_args("libx264", cq, info) == [
        "-crf",
        "21",
        "-maxrate",
        "6000k",
        "-bufsize",
        "12000k",
        "-preset",
        "veryslow",
    ]


def test_hardware_rate_control_args() -> None:
    info = probe("matroska", "vp9", "opus")
    nvenc = FFmpegService._video_rate_args(
        "h264_nvenc",
        TranscodeConfig(
            rate_mode="cq",
            quality=23,
            video_encoder="nvidia",
            highest_quality=True,
        ),
        info,
    )
    assert nvenc == [
        "-rc",
        "vbr",
        "-cq",
        "23",
        "-b:v",
        "0",
        "-preset",
        "p7",
        "-tune",
        "hq",
    ]
    qsv = FFmpegService._video_rate_args(
        "h264_qsv",
        TranscodeConfig(rate_mode="cq", quality=20, video_encoder="intel"),
        info,
    )
    assert qsv == ["-global_quality", "20"]
    amf = FFmpegService._video_rate_args(
        "h264_amf",
        TranscodeConfig(rate_mode="cbr", video_bitrate="3000", video_encoder="amd"),
        info,
    )
    assert "-rc" in amf and "cbr" in amf


def test_software_image_filter_order_and_padding() -> None:
    info = probe("matroska", "vp9", "opus")
    config = TranscodeConfig(
        scale="1000x1000",
        rotation="90",
        mirror=True,
        force_display_aspect=True,
    )
    filters = FFmpegService._software_filters(info, config)
    assert filters[0].startswith("scale=1000:1000:force_original_aspect_ratio=decrease")
    assert filters[1].startswith("pad=1000:1000")
    assert filters[2:] == ["transpose=1", "hflip", "setsar=1", "setdar=1000/1000"]


def test_audio_copy_fallback_conversion_and_downmix() -> None:
    compatible = probe("mov,mp4", "h264", "aac")
    assert FFmpegService._audio_args(compatible, TranscodeConfig()) == (
        ["-c:a", "copy"],
        "aac",
    )
    incompatible = probe(
        "matroska",
        "h264",
        "opus",
        audio_channels=6,
        audio_channel_layout="5.1",
    )
    fallback, codec = FFmpegService._audio_args(incompatible, TranscodeConfig())
    assert codec == "aac"
    assert fallback[:4] == ["-c:a", "aac", "-b:a", "256k"]

    converted, codec = FFmpegService._audio_args(
        incompatible,
        TranscodeConfig(
            audio_convert=True,
            audio_codec="mp3",
            audio_bitrate_kbps=500,
            audio_channels="stereo",
            audio_sample_rate=44100,
        ),
    )
    assert codec == "mp3"
    assert ["-b:a", "320k"] == converted[2:4]
    assert "-af" in converted and "pan=stereo" in converted[converted.index("-af") + 1]


def test_audio_only_conversion_does_not_decode_video_to_hardware_frames(tmp_path: Path) -> None:
    service = FFmpegService()
    info = probe("matroska", "h264", "opus")
    args, _ = service._build_args(
        tmp_path / "source.mkv",
        tmp_path / "target.mp4",
        "audio",
        "h264_nvenc",
        TranscodeConfig(video_encoder="nvidia", audio_convert=True, audio_codec="aac"),
        info,
    )
    assert "-hwaccel" not in args
    assert args[args.index("-c:v") + 1] == "copy"


def test_two_pass_commands_reuse_filters_and_disable_first_pass_audio(tmp_path: Path) -> None:
    service = FFmpegService()
    info = probe("matroska", "vp9", "opus")
    config = TranscodeConfig(
        scale="auto:720",
        rate_mode="vbr",
        video_bitrate="2500",
        two_pass=True,
    )
    first, _ = service._build_args(
        tmp_path / "source.mkv",
        None,
        "both",
        "libx264",
        config,
        info,
        pass_number=1,
        passlog=tmp_path / ".pass",
    )
    second, _ = service._build_args(
        tmp_path / "source.mkv",
        tmp_path / "target.mp4",
        "both",
        "libx264",
        config,
        info,
        pass_number=2,
        passlog=tmp_path / ".pass",
    )
    assert "-an" in first
    assert first[first.index("-pass") + 1] == "1"
    assert second[second.index("-pass") + 1] == "2"
    assert first[first.index("-vf") + 1] == second[second.index("-vf") + 1]


def test_transcode_suffix_modes() -> None:
    auto = TranscodeConfig(suffix_mode="auto")
    custom = TranscodeConfig(suffix_mode="custom", custom_suffix="兼容:版")
    none = TranscodeConfig(suffix_mode="none")
    assert FFmpegService.output_suffix(auto, "h264", "aac") == "_H264_AAC"
    assert FFmpegService.output_suffix(custom, "h264", "aac") == "_兼容_版"
    assert FFmpegService.output_suffix(none, "h264", "aac") == ""
