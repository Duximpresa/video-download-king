from __future__ import annotations

from .models import DownloadRequest, FormatInfo


PRESET_HEIGHTS = {
    "2160p": 2160,
    "1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
}


def video_formats(formats: list[FormatInfo]) -> list[FormatInfo]:
    return sorted(
        (item for item in formats if item.has_video),
        key=lambda item: (item.height or 0, item.fps or 0, item.tbr or 0),
        reverse=True,
    )


def audio_formats(formats: list[FormatInfo]) -> list[FormatInfo]:
    return sorted(
        (item for item in formats if item.has_audio and not item.has_video),
        key=lambda item: (item.abr or item.tbr or 0),
        reverse=True,
    )


def format_selector(request: DownloadRequest) -> str:
    if request.mode == "advanced":
        if not request.video_format_id:
            raise ValueError("高级模式必须选择视频流")
        if request.audio_format_id:
            return f"{request.video_format_id}+{request.audio_format_id}"
        return request.video_format_id
    if request.mode == "audio":
        return "bestaudio/best"
    if request.mode == "video_only":
        if request.quality_preset == "best":
            return "bestvideo"
        if request.quality_preset == "worst":
            return "worstvideo"
        height = request.custom_height if request.quality_preset == "custom" else PRESET_HEIGHTS.get(request.quality_preset)
        if height:
            return f"bestvideo[height<=?{height}]/worstvideo"
        raise ValueError("未知画质预设")
    if request.quality_preset == "best":
        return "bestvideo*+bestaudio/best"
    if request.quality_preset == "worst":
        return "worstvideo*+worstaudio/worst"
    height = request.custom_height if request.quality_preset == "custom" else PRESET_HEIGHTS.get(request.quality_preset)
    if height:
        return (
            f"bestvideo*[height<=?{height}]+bestaudio/"
            f"best[height<=?{height}]/worstvideo*+bestaudio/worst"
        )
    raise ValueError("未知画质预设")
