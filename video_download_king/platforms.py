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
    if host == "b23.tv" or host == "bilibili.com" or host.endswith(".bilibili.com"):
        return "哔哩哔哩"
    if host == "x.com" or host.endswith(".x.com") or host == "twitter.com" or host.endswith(".twitter.com"):
        return "X"
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
    if platform not in {"YouTube", "哔哩哔哩", "X"}:
        raise ValueError("仅支持 YouTube、X 或哔哩哔哩视频链接")
    if platform == "X":
        path = urlparse(url if "://" in url else f"https://{url}").path
        if not re.fullmatch(r"/[^/]+/status/\d+(?:/video/\d+)?/?", path, re.IGNORECASE):
            raise ValueError("X 平台仅支持单条帖子或帖子内视频链接")
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
