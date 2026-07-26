from __future__ import annotations

import re
from urllib.parse import urlparse


DOUYIN_URL_RE = re.compile(
    r"(?:(?:https?://)?(?:www\.)?(?:douyin\.com|v\.douyin\.com|v\.iesdouyin\.com|iesdouyin\.com)/[^\s]+)",
    re.IGNORECASE,
)
XIAOHONGSHU_URL_RE = re.compile(
    r"(?:(?:https?://)?(?:www\.)?xiaohongshu\.com/[^\s]+|(?:https?://)?xhslink\.com/[^\s]+)",
    re.IGNORECASE,
)

PROXY_RECOMMENDED_HOSTS = {
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
}

INSTAGRAM_SINGLE_PATH_RE = re.compile(
    r"^/(?:(?:p|tv|reels?)/[^/]+|(?!(?:share)/)[^/]+/reels?/[^/]+)/?$",
    re.IGNORECASE,
)
TIKTOK_VIDEO_PATH_RE = re.compile(
    r"^/@[\w.-]+/video/\d+/?$",
    re.IGNORECASE,
)
TIKTOK_RESOLVED_VIDEO_PATH_RE = re.compile(
    r"^/@(?:[\w.-]+)?/video/\d+/?$",
    re.IGNORECASE,
)


def detect_platform(url: str) -> str:
    candidate = extract_douyin_url(url) or extract_xiaohongshu_url(url) or url
    if candidate and "://" not in candidate:
        candidate = f"https://{candidate}"
    host = (urlparse(candidate).hostname or "").lower()
    if host == "youtu.be" or host.endswith("youtube.com"):
        return "YouTube"
    if host == "b23.tv" or host == "bilibili.com" or host.endswith(".bilibili.com"):
        return "哔哩哔哩"
    if host == "x.com" or host.endswith(".x.com") or host == "twitter.com" or host.endswith(".twitter.com"):
        return "X"
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "Instagram"
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "TikTok"
    if host == "douyin.com" or host.endswith(".douyin.com") or host.endswith(".iesdouyin.com"):
        return "Douyin"
    if host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com") or host == "xhslink.com" or host.endswith(".xhslink.com"):
        return "小红书"
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
    if matched == "tiktok.com":
        return "TikTok"
    return "X"


def validate_first_version_url(url: str) -> str:
    platform = detect_platform(url)
    if platform not in {"YouTube", "Instagram", "TikTok", "哔哩哔哩", "X"}:
        raise ValueError("仅支持 YouTube、Instagram、TikTok、X 或哔哩哔哩视频链接")
    normalized_url = url if "://" in url else f"https://{url}"
    parsed = urlparse(normalized_url)
    if platform == "X":
        path = parsed.path
        if not re.fullmatch(r"/[^/]+/status/\d+(?:/video/\d+)?/?", path, re.IGNORECASE):
            raise ValueError("X 平台仅支持单条帖子或帖子内视频链接")
    elif platform == "Instagram":
        if not INSTAGRAM_SINGLE_PATH_RE.fullmatch(parsed.path):
            raise ValueError("Instagram 仅支持单个 Reel、视频帖子或 IGTV 链接")
    elif platform == "TikTok":
        host = (parsed.hostname or "").lower()
        is_standard_video = host in {"tiktok.com", "www.tiktok.com"} and bool(
            TIKTOK_VIDEO_PATH_RE.fullmatch(parsed.path)
        )
        is_vm_short = host in {"vm.tiktok.com", "vt.tiktok.com"} and bool(
            re.fullmatch(r"/\w+/?", parsed.path, re.IGNORECASE)
        )
        is_web_short = host in {"tiktok.com", "www.tiktok.com"} and bool(
            re.fullmatch(r"/t/\w+/?", parsed.path, re.IGNORECASE)
        )
        if not (is_standard_video or is_vm_short or is_web_short):
            raise ValueError("TikTok 仅支持单个视频长链或分享短链")
    return platform


def is_tiktok_canonical_video_url(url: str) -> bool:
    candidate = (url or "").strip()
    if candidate and "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    return host in {"tiktok.com", "www.tiktok.com"} and bool(
        TIKTOK_RESOLVED_VIDEO_PATH_RE.fullmatch(parsed.path)
    )


def extract_douyin_url(text: str) -> str | None:
    match = DOUYIN_URL_RE.search((text or "").strip())
    if not match:
        return None
    url = match.group(0).rstrip("，。！？、；：,.;:!?)]}>'\"")
    return url if "://" in url else f"https://{url}"


def extract_xiaohongshu_url(text: str) -> str | None:
    match = XIAOHONGSHU_URL_RE.search((text or "").strip())
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
