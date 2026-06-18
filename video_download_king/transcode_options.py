from __future__ import annotations

import math
import re
from dataclasses import dataclass


VIDEO_BITRATE_PRESETS = (
    "50000",
    "40000",
    "30000",
    "25000",
    "20000",
    "15000",
    "10000",
    "8000",
    "5000",
    "3000",
    "2500",
    "2000",
    "1500",
    "1000",
    "500",
    "最好",
    "好的",
    "auto",
)

MAX_BITRATE_PRESETS = (*VIDEO_BITRATE_PRESETS[:15], "auto")

AUDIO_BITRATE_PRESETS = (
    1536,
    1344,
    1152,
    960,
    768,
    640,
    512,
    448,
    384,
    320,
    256,
    192,
    160,
    128,
    96,
    64,
    32,
)

SCALE_PRESETS = (
    "源尺寸",
    "1:2",
    "1:4",
    "1:8",
    "1:16",
    "3840:auto",
    "1920:auto",
    "auto:2160",
    "auto:1080",
    "auto:720",
    "4096x2160",
    "3840x2160",
    "2560x1440",
    "1920x1080",
    "1440x1080",
    "1280x720",
    "1024x768",
    "1024x576",
    "1000x1000",
    "854x480",
    "720x576",
    "640x360",
    "500x500",
    "320x180",
    "200x200",
    "100x100",
    "50x50",
)

_FIXED_RE = re.compile(r"^(\d+)[xX×](\d+)$")
_AUTO_RE = re.compile(r"^(auto|\d+):(auto|\d+)$", re.IGNORECASE)
_RATIO_RE = re.compile(r"^1:(\d+)$")


@dataclass(slots=True, frozen=True)
class ScaleDecision:
    expression: str
    width: int
    height: int
    kind: str


def even_dimension(value: float) -> int:
    rounded = max(2, int(round(value)))
    return rounded if rounded % 2 == 0 else rounded + 1


def portrait_expression(expression: str, portrait: bool) -> str:
    value = expression.strip()
    if value == "源尺寸" or _RATIO_RE.fullmatch(value):
        return value
    match = _FIXED_RE.fullmatch(value)
    if match:
        width, height = int(match.group(1)), int(match.group(2))
        if (portrait and width > height) or (not portrait and width < height):
            return f"{height}x{width}"
        return value
    match = _AUTO_RE.fullmatch(value)
    if match and (match.group(1).lower() == "auto") != (match.group(2).lower() == "auto"):
        left_auto = match.group(1).lower() == "auto"
        if (portrait and left_auto) or (not portrait and not left_auto):
            return f"{match.group(2)}:{match.group(1)}"
    return value


def resolve_scale(
    expression: str,
    source_width: int | None,
    source_height: int | None,
    *,
    portrait: bool = False,
    no_upscale: bool = False,
) -> ScaleDecision:
    width = source_width or 1920
    height = source_height or 1080
    value = portrait_expression(expression or "源尺寸", portrait)
    if value == "源尺寸":
        return ScaleDecision(value, even_dimension(width), even_dimension(height), "source")

    match = _RATIO_RE.fullmatch(value)
    if match:
        divisor = int(match.group(1))
        if divisor <= 0:
            raise ValueError("比例除数必须大于 0")
        out_width = even_dimension(width / divisor)
        out_height = even_dimension(height / divisor)
        return ScaleDecision(value, out_width, out_height, "ratio")

    match = _FIXED_RE.fullmatch(value)
    if match:
        out_width = even_dimension(int(match.group(1)))
        out_height = even_dimension(int(match.group(2)))
        if no_upscale and (out_width > width or out_height > height):
            return ScaleDecision(value, even_dimension(width), even_dimension(height), "source")
        return ScaleDecision(value, out_width, out_height, "fixed")

    match = _AUTO_RE.fullmatch(value)
    if match:
        left, right = match.groups()
        if left.lower() == "auto" and right.lower() == "auto":
            raise ValueError("比例不能同时使用 auto")
        if left.lower() != "auto" and right.lower() != "auto":
            raise ValueError("自适应比例必须有一边是 auto")
        if left.lower() == "auto":
            out_height = even_dimension(int(right))
            out_width = even_dimension(out_height * width / height)
        else:
            out_width = even_dimension(int(left))
            out_height = even_dimension(out_width * height / width)
        if no_upscale and (out_width > width or out_height > height):
            return ScaleDecision(value, even_dimension(width), even_dimension(height), "source")
        return ScaleDecision(value, out_width, out_height, "auto")

    raise ValueError("比例格式应为 宽x高、宽:auto、auto:高 或 1:N")


def shutter_auto_bitrate(width: int, height: int, fps: float | None, tier: str = "auto") -> int:
    frame_rate = fps if fps and fps > 0 else 25.0
    base = max(100, round(width * height * frame_rate * 8 * 2 / 165888))
    multiplier = {"auto": 1, "好的": 2, "最好": 4}.get(tier)
    if multiplier is None:
        raise ValueError(f"未知视频码率档位：{tier}")
    return base * multiplier


def resolve_video_bitrate(
    value: str | int,
    width: int,
    height: int,
    fps: float | None,
) -> int:
    text = str(value).strip().lower()
    localized = {"best": "最好", "good": "好的", "自动": "auto"}.get(text, text)
    if localized in {"auto", "最好", "好的"}:
        return shutter_auto_bitrate(width, height, fps, localized)
    try:
        bitrate = int(localized)
    except ValueError as exc:
        raise ValueError("视频码率必须是正整数或 auto/好的/最好") from exc
    if bitrate <= 0:
        raise ValueError("视频码率必须大于 0")
    return bitrate


def resolve_quality(value: str | int) -> int:
    text = str(value).strip()
    if text in {"最好", "best"}:
        return 1
    if text in {"最差", "worst"}:
        return 51
    try:
        return max(1, min(51, int(text)))
    except ValueError as exc:
        raise ValueError("CQ 值必须在 1–51 之间") from exc


def estimate_size_mib(
    duration: float | None,
    video_bitrate_kbps: int,
    audio_bitrate_kbps: int,
) -> float | None:
    if not duration or duration <= 0:
        return None
    return (video_bitrate_kbps + audio_bitrate_kbps) * duration / 8 / 1024


def bitrate_for_target_size(
    duration: float | None,
    target_size_mib: float,
    audio_bitrate_kbps: int,
) -> int:
    if not duration or duration <= 0:
        raise ValueError("缺少有效时长，无法按文件大小计算码率")
    if target_size_mib <= 0:
        raise ValueError("目标文件大小必须大于 0")
    total_kbps = target_size_mib * 8 * 1024 / duration
    return max(100, math.floor(total_kbps - audio_bitrate_kbps))


def clamp_audio_bitrate(codec: str, bitrate: int | None) -> int | None:
    if codec in {"copy", "none"}:
        return None
    defaults = {"aac": 256, "mp3": 256, "ac3": 384}
    limits = {"aac": (32, 512), "mp3": (32, 320), "ac3": (96, 640)}
    selected = bitrate or defaults[codec]
    low, high = limits[codec]
    return max(low, min(high, int(selected)))
