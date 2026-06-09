from video_download_king.models import TranscodeConfig
from video_download_king.transcode import FFmpegService, ProbeInfo


def probe(container: str, video: str, audio: str) -> ProbeInfo:
    return ProbeInfo(set(container.split(",")), video, audio, height=1080)


def test_transcode_decisions() -> None:
    assert FFmpegService.decide_action(probe("mov,mp4", "h264", "aac")) == "none"
    assert FFmpegService.decide_action(probe("matroska", "h264", "aac")) == "remux"
    assert FFmpegService.decide_action(probe("matroska", "h264", "opus")) == "audio"
    assert FFmpegService.decide_action(probe("matroska", "vp9", "aac")) == "video"
    assert FFmpegService.decide_action(probe("matroska", "vp9", "opus")) == "both"


def test_video_rate_control_args() -> None:
    info = probe("matroska", "vp9", "opus")
    quality = TranscodeConfig(rate_mode="quality", quality=21)
    assert FFmpegService._video_quality_args("libx264", quality, info) == ["-crf", "21", "-preset", "medium"]
    bitrate = TranscodeConfig(rate_mode="bitrate", video_bitrate_kbps=6000)
    assert FFmpegService._video_quality_args("h264_nvenc", bitrate, info) == ["-b:v", "6000k"]
    automatic = TranscodeConfig(rate_mode="auto")
    assert FFmpegService._video_quality_args("libx264", automatic, info) == ["-b:v", "5000k"]


def test_auto_video_bitrate_priority() -> None:
    assert FFmpegService.auto_video_bitrate(
        ProbeInfo({"mkv"}, "vp9", "opus", video_bitrate=3_250_000)
    ) == 3250
    assert FFmpegService.auto_video_bitrate(
        ProbeInfo({"mkv"}, "vp9", "opus", audio_bitrate=128_000, format_bitrate=2_128_000)
    ) == 2000
    assert FFmpegService.auto_video_bitrate(
        ProbeInfo({"mkv"}, "vp9", "opus", audio_bitrate=128_000, file_size=26_600_000, duration=100)
    ) == 2000
    assert FFmpegService.auto_video_bitrate(ProbeInfo({"mkv"}, "vp9", "opus"), 1800) == 1800
    assert FFmpegService.auto_video_bitrate(ProbeInfo({"mkv"}, "vp9", "opus", height=720)) == 2500


def test_codec_aware_automatic_rate_decisions() -> None:
    expected = {
        "h264": (1.0, 1.0),
        "vp8": (1.3, 1.3),
        "vp9": (1.8, 2.0),
        "hevc": (2.0, 2.2),
        "av1": (2.0, 2.2),
        "mpeg4": (1.0, 1.0),
        "mpeg2video": (1.0, 1.0),
    }
    for codec, (cpu_factor, gpu_factor) in expected.items():
        info = ProbeInfo({"mkv"}, codec, "opus", video_bitrate=2_000_000, height=1080)
        cpu = FFmpegService.automatic_rate_decision(info, TranscodeConfig(processor="cpu"))
        gpu = FFmpegService.automatic_rate_decision(info, TranscodeConfig(processor="gpu"))
        assert cpu.strategy == "bitrate"
        assert cpu.multiplier == cpu_factor
        assert cpu.target_bitrate_kbps == round(2000 * cpu_factor)
        assert gpu.multiplier == gpu_factor
        assert gpu.target_bitrate_kbps == round(2000 * gpu_factor)


def test_unknown_codec_uses_constrained_quality() -> None:
    info = ProbeInfo({"mkv"}, "future_codec", "opus", video_bitrate=2_000_000, height=1080)
    config = TranscodeConfig(rate_mode="auto", processor="gpu")
    decision = FFmpegService.automatic_rate_decision(info, config)
    assert decision.strategy == "constrained_quality"
    assert decision.quality == 23
    assert decision.maxrate_kbps == 4000
    assert decision.bufsize_kbps == 8000
    args = FFmpegService._video_quality_args("h264_nvenc", config, info)
    assert args == [
        "-rc", "vbr", "-cq", "23", "-b:v", "0", "-preset", "p5",
        "-maxrate", "4000k", "-bufsize", "8000k",
    ]


def test_unknown_codec_without_bitrate_uses_resolution_guardrail() -> None:
    info = ProbeInfo({"mkv"}, "future_codec", "opus", height=720)
    decision = FFmpegService.automatic_rate_decision(info, TranscodeConfig())
    assert decision.maxrate_kbps == 5000
    assert decision.bufsize_kbps == 10000


def test_transcode_suffix_modes() -> None:
    auto = TranscodeConfig(suffix_mode="auto")
    custom = TranscodeConfig(suffix_mode="custom", custom_suffix="兼容:版")
    none = TranscodeConfig(suffix_mode="none")
    assert FFmpegService.output_suffix(auto, "h264", "aac") == "_H264_AAC"
    assert FFmpegService.output_suffix(custom, "h264", "aac") == "_兼容_版"
    assert FFmpegService.output_suffix(none, "h264", "aac") == ""
