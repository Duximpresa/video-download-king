from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class CookieStatus:
    state: str
    text: str


_PLATFORM_DOMAINS = {
    "YouTube": ("youtube.com", "google.com"),
    "Instagram": ("instagram.com",),
    "TikTok": ("tiktok.com",),
    "X": ("x.com", "twitter.com"),
    "Douyin": ("douyin.com", "iesdouyin.com"),
    "Bilibili": ("bilibili.com",),
    "哔哩哔哩": ("bilibili.com",),
    "Xiaohongshu": ("xiaohongshu.com",),
    "小红书": ("xiaohongshu.com",),
}

_LOGIN_COOKIE_NAMES = {
    "YouTube": {"SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "SID"},
    "Instagram": {"sessionid"},
    "TikTok": {"sessionid", "sessionid_ss", "sid_tt"},
    "X": {"auth_token"},
    "Douyin": {"sessionid", "sessionid_ss", "sid_tt"},
    "Bilibili": {"SESSDATA"},
    "哔哩哔哩": {"SESSDATA"},
    "Xiaohongshu": {"web_session"},
    "小红书": {"web_session"},
}


def inspect_cookie_status(
    platform: str,
    cookie_file: str = "",
    cookie_browser: str = "",
) -> CookieStatus:
    """Inspect local login-cookie evidence without claiming a server-side login check."""
    if cookie_file:
        path = Path(cookie_file).expanduser()
        if not path.is_file():
            return CookieStatus("invalid", "Cookie 无效：文件不存在")
        try:
            rows = _active_platform_cookie_names(path, platform)
        except OSError:
            return CookieStatus("invalid", "Cookie 无效：文件无法读取")
        if not rows:
            return CookieStatus("invalid", "Cookie 可能失效：没有该平台未过期的 Cookie")
        login_names = _LOGIN_COOKIE_NAMES.get(platform, set())
        if rows.intersection(login_names):
            return CookieStatus("valid", "Cookie 看起来有效：检测到未过期的登录凭据")
        return CookieStatus("warning", "Cookie 已加载，但未检测到登录凭据；可能只能获取游客画质")
    if cookie_browser:
        browser = {"chrome": "Chrome", "edge": "Edge"}.get(cookie_browser, cookie_browser)
        return CookieStatus("browser", f"已启用 {browser} Cookie；登录有效性以网站返回画质为准")
    return CookieStatus("missing", "未配置 Cookie；部分平台可能只能获取低清或受限格式")


def _active_platform_cookie_names(path: Path, platform: str) -> set[str]:
    domains = _PLATFORM_DOMAINS.get(platform, ())
    now = int(time.time())
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("#HttpOnly_"):
            line = line.removeprefix("#HttpOnly_")
        elif not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain, _include_subdomains, _cookie_path, _secure, expires, name, value = fields[:7]
        normalized_domain = domain.lstrip(".").lower()
        if domains and not any(
            normalized_domain == expected or normalized_domain.endswith(f".{expected}")
            for expected in domains
        ):
            continue
        try:
            expiry = int(expires or 0)
        except ValueError:
            expiry = 0
        if not value or (expiry and expiry <= now):
            continue
        names.add(name)
    return names
