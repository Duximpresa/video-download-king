from __future__ import annotations

from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkRequest
from PySide6.QtCore import QUrl

from .models import ProxyConfig


_REFERERS = {
    "YouTube": "https://www.youtube.com/",
    "Instagram": "https://www.instagram.com/",
    "TikTok": "https://www.tiktok.com/",
    "X": "https://x.com/",
    "Douyin": "https://www.douyin.com/",
    "Bilibili": "https://www.bilibili.com/",
    "哔哩哔哩": "https://www.bilibili.com/",
    "Xiaohongshu": "https://www.xiaohongshu.com/",
    "小红书": "https://www.xiaohongshu.com/",
}


def configure_preview_proxy(manager: QNetworkAccessManager, proxy: ProxyConfig) -> None:
    if proxy.scheme == "direct":
        manager.setProxy(QNetworkProxy(QNetworkProxy.NoProxy))
        return
    proxy_type = QNetworkProxy.Socks5Proxy if proxy.scheme.startswith("socks") else QNetworkProxy.HttpProxy
    configured = QNetworkProxy(proxy_type, proxy.host, proxy.port or 0, proxy.username, proxy.password)
    manager.setProxy(configured)


def thumbnail_request(url: str, platform: str) -> QNetworkRequest:
    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(
        b"User-Agent",
        b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        b"(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    )
    request.setRawHeader(b"Accept", b"image/avif,image/webp,image/apng,image/*,*/*;q=0.8")
    referer = _REFERERS.get(platform)
    if referer:
        request.setRawHeader(b"Referer", referer.encode("ascii"))
    request.setAttribute(
        QNetworkRequest.RedirectPolicyAttribute,
        QNetworkRequest.NoLessSafeRedirectPolicy,
    )
    return request
