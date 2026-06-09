from __future__ import annotations

from urllib.parse import urlparse


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host == "youtu.be" or host.endswith("youtube.com"):
        return "YouTube"
    return "未知平台"


def validate_first_version_url(url: str) -> str:
    platform = detect_platform(url)
    if platform != "YouTube":
        raise ValueError("第一版仅支持 YouTube 单链接")
    return platform

