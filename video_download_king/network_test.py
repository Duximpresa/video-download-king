from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

import aiohttp
from aiohttp_socks import ProxyConnector
from PySide6.QtCore import QObject, Signal, Slot

from . import __version__
from .models import ProxyConfig


def validate_test_url(url: str) -> str:
    candidate = (url or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("测试网址必须是完整的 HTTP 或 HTTPS 地址")
    return candidate


async def test_connectivity(url: str, proxy: ProxyConfig, timeout: int) -> tuple[int, int]:
    target = validate_test_url(url)
    proxy_url = proxy.url()
    connector = None
    request_proxy = proxy_url
    if proxy_url and proxy.scheme in {"socks4", "socks5"}:
        connector = ProxyConnector.from_url(proxy_url)
        request_proxy = None
    client_timeout = aiohttp.ClientTimeout(total=max(5, min(timeout, 60)))
    started = time.perf_counter()
    async with aiohttp.ClientSession(
        timeout=client_timeout,
        connector=connector,
        headers={"User-Agent": f"VideoDownloadKing/{__version__} connectivity-test"},
    ) as session:
        async with session.get(
            target,
            proxy=request_proxy,
            allow_redirects=True,
        ) as response:
            await response.content.read(1)
            status = response.status
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    if status >= 400:
        raise RuntimeError(f"目标网站返回 HTTP {status}")
    return status, elapsed_ms


class NetworkTestWorker(QObject):
    completed = Signal(bool, str)
    finished = Signal()

    def __init__(self, url: str, proxy: ProxyConfig, timeout: int) -> None:
        super().__init__()
        self.url = url
        self.proxy = proxy
        self.timeout = timeout

    @Slot()
    def run(self) -> None:
        try:
            status, elapsed_ms = asyncio.run(
                test_connectivity(self.url, self.proxy, self.timeout)
            )
            self.completed.emit(True, f"连接成功：HTTP {status}，耗时 {elapsed_ms} ms")
        except Exception as exc:
            self.completed.emit(False, f"连接失败：{exc}")
        finally:
            self.finished.emit()
