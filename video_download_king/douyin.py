from __future__ import annotations

import asyncio
import json
import os
import random
import re
import shutil
import string
import time
from collections.abc import Callable
from datetime import datetime
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import aiohttp
import aiofiles
from aiohttp_socks import ProxyConnector

from .douyin_vendor.abogus import ABogus, BrowserFingerprintGenerator
from .douyin_vendor.xbogus import XBogus
from .models import (
    DouyinAsset,
    DouyinDownloadRequest,
    DouyinMediaInfo,
    TaskProgress,
)
from .platforms import validate_douyin_url
from .processes import ProcessCancelled
from .utils import render_filename_template, sanitize_filename, unique_path


ProgressCallback = Callable[[TaskProgress], None]
LogCallback = Callable[[str], None]

_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
)
_SHORT_HOSTS = {"v.douyin.com", "v.iesdouyin.com", "iesdouyin.com"}
_ID_RE = re.compile(r"/(?:video|note|gallery|slides)/(\d+)|[?&]modal_id=(\d+)")
_IMAGE_SUFFIXES = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def resolve_douyin_output_dir(request: DouyinDownloadRequest, author: str = "") -> Path:
    output_dir = request.output_dir
    if request.classify_by_platform:
        output_dir = output_dir / "Douyin"
    if request.classify_by_author:
        output_dir = output_dir / sanitize_filename(author or "未知作者", 80)
    return output_dir


def load_netscape_cookies(path: str) -> dict[str, str]:
    if not path:
        return {}
    cookie_path = Path(path)
    if not cookie_path.exists():
        raise ValueError(f"抖音 Cookie 文件不存在：{cookie_path}")
    jar = MozillaCookieJar(str(cookie_path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as exc:
        raise ValueError(f"无法读取 Netscape cookies.txt：{exc}") from exc
    return {
        cookie.name: cookie.value
        for cookie in jar
        if "douyin.com" in (cookie.domain or "") or "iesdouyin.com" in (cookie.domain or "")
    }


def _urls(source: Any) -> list[str]:
    if isinstance(source, dict):
        source = source.get("url_list") or source.get("urlList") or []
    if isinstance(source, str):
        return [source] if source else []
    if isinstance(source, list):
        return [item for item in source if isinstance(item, str) and item]
    return []


def _all_urls(*sources: Any) -> tuple[str, ...]:
    result: list[str] = []
    for source in sources:
        for url in _urls(source):
            if url not in result:
                result.append(url)
    return tuple(
        sorted(
            result,
            key=lambda value: (
                any(marker in value.lower() for marker in ("watermark=1", "playwm", "owner_watermark")),
                ".webp" in urlparse(value).path.lower(),
            ),
        )
    )


def _gallery_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    image_post = data.get("image_post_info")
    if isinstance(image_post, dict):
        for key in ("images", "image_list"):
            items = image_post.get(key)
            if isinstance(items, list) and items:
                return [item for item in items if isinstance(item, dict)]
    items = data.get("images") or data.get("image_list") or []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def select_video_asset(assets: list[DouyinAsset], quality: str) -> DouyinAsset:
    if not assets:
        raise ValueError("该作品没有可下载的视频流")

    def resolution(item: DouyinAsset) -> int:
        dimensions = [value for value in (item.width, item.height) if value and value > 0]
        return min(dimensions) if dimensions else 0

    rated = [item for item in assets if item.bitrate and item.bitrate > 0]
    complete = [item for item in rated if item.codec.lower().endswith("_0")]
    candidates = complete or rated or [item for item in assets if not item.watermarked] or assets
    if quality == "lowest":
        return min(candidates, key=lambda item: (item.bitrate or 0, resolution(item)))
    if quality == "highest":
        return max(candidates, key=lambda item: (item.bitrate or 0, resolution(item)))
    target = int(quality.removesuffix("p"))
    return min(
        candidates,
        key=lambda item: (
            abs(resolution(item) - target),
            -(item.bitrate or 0),
        ),
    )


class DouyinService:
    BASE_URL = "https://www.douyin.com"

    def __init__(self) -> None:
        self.cancelled = False
        self.user_agent = random.choice(_USER_AGENTS)
        self.xbogus = XBogus(self.user_agent)

    def cancel(self) -> None:
        self.cancelled = True

    def analyze(self, request: DouyinDownloadRequest, on_log: LogCallback | None = None) -> DouyinMediaInfo:
        self.cancelled = False
        return asyncio.run(self._analyze(request, on_log or (lambda _text: None)))

    async def _analyze(self, request: DouyinDownloadRequest, on_log: LogCallback) -> DouyinMediaInfo:
        cookies = load_netscape_cookies(request.cookie_file)
        headers = self._headers(cookies)
        timeout = aiohttp.ClientTimeout(total=max(5, request.timeout))
        connector, request_proxy = self._proxy_options(request.proxy.url())
        async with aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector) as session:
            url = validate_douyin_url(request.url)
            if (urlparse(url).hostname or "").lower() in _SHORT_HOSTS:
                on_log("正在解析抖音短链接")
                async with session.get(url, allow_redirects=True, proxy=request_proxy) as response:
                    if response.status >= 400:
                        raise RuntimeError(f"抖音短链接解析失败：HTTP {response.status}")
                    url = str(response.url)
            media_id = self._extract_id(url)
            detail = await self._get_detail(
                session,
                media_id,
                cookies,
                request_proxy,
                on_log,
            )
        return self._media_from_detail(url, detail)

    @staticmethod
    def _proxy_options(proxy: str | None) -> tuple[ProxyConnector | None, str | None]:
        if proxy and proxy.lower().startswith(("socks4://", "socks5://")):
            return ProxyConnector.from_url(proxy), None
        return None, proxy

    @staticmethod
    def _headers(cookies: dict[str, str]) -> dict[str, str]:
        headers = {
            "User-Agent": random.choice(_USER_AGENTS),
            "Referer": "https://www.douyin.com/?recommend=1",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        }
        if cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
        return headers

    @staticmethod
    def _extract_id(url: str) -> str:
        match = _ID_RE.search(url)
        if not match:
            raise ValueError("无法从抖音链接中识别作品 ID")
        return next(group for group in match.groups() if group)

    @staticmethod
    def _ms_token(cookies: dict[str, str]) -> str:
        return cookies.get("msToken") or (
            "".join(random.choice(string.ascii_letters + string.digits) for _ in range(182)) + "=="
        )

    def _default_query(self, cookies: dict[str, str], aid: str) -> dict[str, str]:
        return {
            "device_platform": "webapp",
            "aid": aid,
            "channel": "channel_pc_web",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": "1536",
            "screen_height": "864",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "139.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "139.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "16",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "200",
            "support_h265": "1",
            "support_dash": "1",
            "msToken": self._ms_token(cookies),
        }

    def _signed_url(self, path: str, params: dict[str, str]) -> tuple[str, str]:
        query = urlencode(params)
        try:
            fp = BrowserFingerprintGenerator.generate_fingerprint("Chrome")
            signer = ABogus(fp=fp, user_agent=self.user_agent)
            signed, _token, ua, _body = signer.generate_abogus(query, "")
            return f"{self.BASE_URL}{path}?{signed}", ua
        except Exception:
            url, _token, ua = self.xbogus.build(f"{self.BASE_URL}{path}?{query}")
            return url, ua

    async def _get_detail(
        self,
        session: aiohttp.ClientSession,
        media_id: str,
        cookies: dict[str, str],
        proxy: str | None,
        on_log: LogCallback,
    ) -> dict[str, Any]:
        last_error = ""
        for aid in ("6383", "1128"):
            params = self._default_query(cookies, aid)
            params["aweme_id"] = media_id
            for attempt, delay in enumerate((1, 2, 5), start=1):
                if self.cancelled:
                    raise ProcessCancelled("任务已取消")
                url, ua = self._signed_url("/aweme/v1/web/aweme/detail/", params)
                try:
                    async with session.get(url, headers={"User-Agent": ua}, proxy=proxy) as response:
                        body = await response.read()
                        if response.status == 200 and body:
                            data = json.loads(body.decode("utf-8"))
                            detail = data.get("aweme_detail")
                            if isinstance(detail, dict):
                                return detail
                            reason = (data.get("filter_detail") or {}).get("filter_reason")
                            if reason:
                                on_log(f"接口 aid={aid} 过滤了该作品（{reason}），正在切换接口")
                                break
                        last_error = f"HTTP {response.status} 或空响应"
                except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
                    last_error = str(exc)
                if attempt < 3:
                    on_log(f"抖音详情请求失败，第 {attempt} 次重试")
                    await asyncio.sleep(delay)
        hint = "，请在设置中提供新鲜的抖音 cookies.txt" if not cookies else "，Cookie 可能已失效"
        raise RuntimeError(f"无法获取抖音作品详情：{last_error or '接口未返回作品'}{hint}")

    @staticmethod
    def _media_from_detail(url: str, data: dict[str, Any]) -> DouyinMediaInfo:
        media_id = str(data.get("aweme_id") or "")
        title = (data.get("desc") or "").strip() or f"抖音作品 {media_id}"
        author = (data.get("author") or {}).get("nickname") or ""
        create_time = data.get("create_time")
        upload_date = datetime.fromtimestamp(create_time).strftime("%Y%m%d") if create_time else ""
        video = data.get("video") if isinstance(data.get("video"), dict) else {}
        cover_urls = _all_urls(video.get("origin_cover"), video.get("cover"), video.get("dynamic_cover"))
        cover = DouyinAsset("cover", cover_urls, extension=".jpg") if cover_urls else None
        gallery_items = _gallery_items(data)
        gallery_assets: list[DouyinAsset] = []
        for index, item in enumerate(gallery_items, start=1):
            image_urls = _all_urls(
                item.get("watermark_free_download_url_list"),
                item,
                item.get("origin_image"),
                item.get("display_image"),
                item.get("download_url"),
                item.get("download_addr"),
                item.get("download_url_list"),
                item.get("owner_watermark_image"),
            )
            if image_urls:
                gallery_assets.append(DouyinAsset("image", image_urls, index=index))
            live_video = item.get("video") if isinstance(item.get("video"), dict) else {}
            live_urls = _all_urls(
                live_video.get("play_addr_h264"),
                live_video.get("play_addr_265"),
                live_video.get("play_addr"),
                live_video.get("download_addr"),
                item.get("video_play_addr"),
                item.get("video_download_addr"),
            )
            if live_urls:
                gallery_assets.append(
                    DouyinAsset("live_photo", live_urls, index=index, extension=".mp4")
                )

        video_assets: list[DouyinAsset] = []
        seen: set[tuple[str, ...]] = set()
        for entry in video.get("bit_rate") or []:
            if not isinstance(entry, dict):
                continue
            address = entry.get("play_addr") if isinstance(entry.get("play_addr"), dict) else {}
            urls = _all_urls(address)
            if not urls or urls in seen:
                continue
            seen.add(urls)
            video_assets.append(
                DouyinAsset(
                    "video",
                    urls,
                    width=address.get("width") or entry.get("width"),
                    height=address.get("height") or entry.get("height"),
                    bitrate=int(entry.get("bit_rate") or 0) or None,
                    codec=str(entry.get("gear_name") or ""),
                    extension=".mp4",
                    uri=str(address.get("uri") or ""),
                )
            )
        for key in ("play_addr_h264", "play_addr_265", "play_addr", "download_addr"):
            address = video.get(key)
            urls = _all_urls(address)
            if not urls or urls in seen:
                continue
            seen.add(urls)
            video_assets.append(
                DouyinAsset(
                    "video",
                    urls,
                    width=address.get("width") if isinstance(address, dict) else None,
                    height=address.get("height") if isinstance(address, dict) else None,
                    bitrate=None,
                    codec=key,
                    extension=".mp4",
                    watermarked=key == "download_addr",
                    uri=str(address.get("uri") or "") if isinstance(address, dict) else "",
                )
            )
        return DouyinMediaInfo(
            webpage_url=url,
            media_id=media_id,
            title=title,
            author=author,
            upload_date=upload_date,
            duration=(video.get("duration") or 0) / 1000 or None,
            thumbnail=cover_urls[0] if cover_urls else "",
            media_type="gallery" if gallery_items else "video",
            video_assets=video_assets,
            gallery_assets=gallery_assets,
            cover_asset=cover,
        )

    def download(
        self,
        request: DouyinDownloadRequest,
        on_progress: ProgressCallback,
        on_log: LogCallback,
    ) -> list[Path]:
        self.cancelled = False
        return asyncio.run(self._download(request, on_progress, on_log))

    async def _download(
        self,
        request: DouyinDownloadRequest,
        on_progress: ProgressCallback,
        on_log: LogCallback,
    ) -> list[Path]:
        media = request.media or await self._analyze(request, on_log)
        output_dir = resolve_douyin_output_dir(request, media.author)
        output_dir.mkdir(parents=True, exist_ok=True)
        staging = output_dir / f".vdk-douyin-{media.media_id}-{time.time_ns()}"
        staging.mkdir(parents=True)
        cookies = load_netscape_cookies(request.cookie_file)
        headers = self._headers(cookies)
        timeout = aiohttp.ClientTimeout(total=None, sock_read=max(30, request.timeout))
        connector, request_proxy = self._proxy_options(request.proxy.url())
        has_index_field = "{index}" in request.filename_template
        has_asset_field = "{asset}" in request.filename_template

        def render_stem(index: int | None, asset_label: str) -> str:
            return render_filename_template(
                request.filename_template,
                {
                    "title": media.title,
                    "id": media.media_id,
                    "channel": media.author,
                    "author": media.author,
                    "platform": "Douyin",
                    "upload_date": media.upload_date,
                    "type": "图集" if media.media_type == "gallery" else "视频",
                    "index": f"{index:02d}" if index is not None else "01",
                    "asset": asset_label,
                },
            )

        tasks: list[tuple[DouyinAsset, Path]] = []
        if media.media_type == "video":
            asset = select_video_asset(media.video_assets, request.quality)
            tasks.append((asset, staging / f"{render_stem(1, '视频')}.mp4"))
        else:
            for asset in media.gallery_assets:
                stem = render_stem(asset.index, "实况" if asset.kind == "live_photo" else "图片")
                marker = "" if has_index_field else f"_{asset.index:02d}"
                if asset.kind == "live_photo" and not has_asset_field:
                    marker += "_live"
                tasks.append((asset, staging / f"{stem}{marker}{asset.extension or '.jpg'}"))
        if request.download_thumbnail and media.cover_asset:
            stem = render_stem(None, "封面")
            suffix = "" if has_asset_field else "_cover"
            tasks.append((media.cover_asset, staging / f"{stem}{suffix}.jpg"))

        completed: list[Path] = []
        failures: list[str] = []
        total = len(tasks)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector) as session:
            for item_index, (asset, path) in enumerate(tasks):
                try:
                    saved = await self._download_asset(
                        session,
                        asset,
                        path,
                        request_proxy,
                        item_index,
                        total,
                        on_progress,
                        on_log,
                    )
                    completed.append(saved)
                except ProcessCancelled:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise
                except Exception as exc:
                    failures.append(f"{path.name}: {exc}")
                    on_log(f"资源下载失败：{path.name}：{exc}")
                    if media.media_type == "video" and asset.kind == "video":
                        shutil.rmtree(staging, ignore_errors=True)
                        raise
        if not completed:
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError("抖音作品的全部资源均下载失败")

        final_paths: list[Path] = []
        for path in completed:
            target = unique_path(output_dir / path.name)
            os.replace(path, target)
            final_paths.append(target)
        shutil.rmtree(staging, ignore_errors=True)
        if failures:
            on_log(f"部分完成：成功 {len(final_paths)} 个，失败 {len(failures)} 个")
        on_progress(TaskProgress("完成", 100, 100, message="抖音资源下载完成"))
        return final_paths

    async def _download_asset(
        self,
        session: aiohttp.ClientSession,
        asset: DouyinAsset,
        path: Path,
        proxy: str | None,
        item_index: int,
        total_items: int,
        on_progress: ProgressCallback,
        on_log: LogCallback,
    ) -> Path:
        last_error = ""
        for attempt, delay in enumerate((1, 2, 5), start=1):
            for url in asset.urls:
                if self.cancelled:
                    raise ProcessCancelled("任务已取消")
                temp = path.with_suffix(path.suffix + ".tmp")
                temp.unlink(missing_ok=True)
                try:
                    async with session.get(url, proxy=proxy) as response:
                        if response.status != 200:
                            last_error = f"HTTP {response.status}"
                            continue
                        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                        if asset.kind in {"image", "cover"} and content_type in _IMAGE_SUFFIXES:
                            path = path.with_suffix(_IMAGE_SUFFIXES[content_type])
                            temp = path.with_suffix(path.suffix + ".tmp")
                        expected = response.content_length
                        written = 0
                        async with aiofiles.open(temp, "wb") as handle:
                            async for chunk in response.content.iter_chunked(256 * 1024):
                                if self.cancelled:
                                    raise ProcessCancelled("任务已取消")
                                await handle.write(chunk)
                                written += len(chunk)
                                stage = written / expected * 100 if expected else None
                                overall = (item_index + (stage or 0) / 100) / max(1, total_items) * 100
                                on_progress(
                                    TaskProgress(
                                        "下载",
                                        overall,
                                        stage,
                                        stage_indeterminate=expected is None,
                                        current_item=path.name,
                                        downloaded_bytes=written,
                                        total_bytes=expected,
                                    )
                                )
                        if expected is not None and written != expected:
                            temp.unlink(missing_ok=True)
                            last_error = f"文件长度不匹配（应为 {expected}，实际 {written}）"
                            continue
                        os.replace(temp, path)
                        return path
                except ProcessCancelled:
                    temp.unlink(missing_ok=True)
                    raise
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                    temp.unlink(missing_ok=True)
                    last_error = str(exc)
            if attempt < 3:
                on_log(f"{path.name} 下载失败，第 {attempt} 次重试")
                await asyncio.sleep(delay)
        raise RuntimeError(last_error or "没有可用的资源地址")
