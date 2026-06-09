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


def test_transcode_suffix_modes() -> None:
    auto = TranscodeConfig(suffix_mode="auto")
    custom = TranscodeConfig(suffix_mode="custom", custom_suffix="兼容:版")
    none = TranscodeConfig(suffix_mode="none")
    assert FFmpegService.output_suffix(auto, "h264", "aac") == "_H264_AAC"
    assert FFmpegService.output_suffix(custom, "h264", "aac") == "_兼容_版"
    assert FFmpegService.output_suffix(none, "h264", "aac") == ""
