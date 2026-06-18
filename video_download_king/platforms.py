from __future__ import annotations

import re
from urllib.parse import urlparse


DOUYIN_URL_RE = re.compile(
    r"(?:(?:https?://)?(?:www\.)?(?:douyin\.com|v\.douyin\.com|v\.iesdouyin\.com|iesdouyin\.com)/[^\s]+)",
    re.IGNORECASE,
)

PROXY_RECOMMENDED_HOSTS = {
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "x.com",
    "twitter.com",
}


def detect_platform(url: str) -> str:
    candidate = extract_douyin_url(url) or url
    if candidate and "://" not in candidate:
        candidate = f"https://{candidate}"
    host = (urlparse(candidate).hostname or "").lower()
    if host == "youtu.be" or host.endswith("youtube.com"):
        return "YouTube"
    if host == "douyin.com" or host.endswith(".douyin.com") or host.endswith(".iesdouyin.com"):
        return "Douyin"
    return "未知平台"


def proxy_recommended_platform(url: str) -> str | None:
    candidate = (url or "").strip()
    if candidate and "://" not in candidate:
        candidate = f"https://{candidate}"
    host = (urlparse(candidate).hostname or "").lower()
    matched = next(
        (
            domain
            for domain in PROXY_RECOMMENDED_HOSTS
            if host == domain or host.endswith(f".{domain}")
        ),
        None,
    )
    if not matched:
        return None
    if matched in {"youtube.com", "youtu.be"}:
        return "YouTube"
    if matched == "instagram.com":
        return "Instagram"
    return "X"


def validate_first_version_url(url: str) -> str:
    platform = detect_platform(url)
    if platform != "YouTube":
        raise ValueError("第一版仅支持 YouTube 单链接")
    return platform


def extract_douyin_url(text: str) -> str | None:
    match = DOUYIN_URL_RE.search((text or "").strip())
    if not match:
        return None
    url = match.group(0).rstrip("，。！？、；：,.;:!?)]}>'\"")
    return url if "://" in url else f"https://{url}"


def validate_douyin_url(text: str) -> str:
    url = extract_douyin_url(text)
    if not url:
        raise ValueError("未找到有效的抖音链接")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not (
        host == "douyin.com"
        or host.endswith(".douyin.com")
        or host.endswith(".iesdouyin.com")
    ):
        raise ValueError("仅支持抖音链接")
    if host in {"v.douyin.com", "v.iesdouyin.com", "iesdouyin.com"}:
        return url
    if re.search(r"/(?:video|note|gallery|slides)/\d+", parsed.path) or re.search(
        r"[?&]modal_id=\d+", url
    ):
        return url
    raise ValueError("首版仅支持抖音单视频或图集作品")
