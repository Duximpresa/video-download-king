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
    assert FFmpegService._video_quality_args("libx264", automatic, info) == ["-b:v", "8000k"]

