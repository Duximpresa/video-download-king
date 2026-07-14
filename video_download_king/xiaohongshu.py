from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from collections.abc import Callable
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import urlparse

import aiofiles
import aiohttp
from aiohttp_socks import ProxyConnector

from .models import (
    TaskProgress,
    XiaohongshuAsset,
    XiaohongshuDownloadRequest,
    XiaohongshuMediaInfo,
)
from .processes import ProcessCancelled
from .utils import render_filename_template, sanitize_filename, unique_path


ProgressCallback = Callable[[TaskProgress], None]
LogCallback = Callable[[str], None]

_URL_RE = re.compile(
    r"(?:(?:https?://)?(?:www\.)?xiaohongshu\.com/(?:explore/|discovery/item/|user/profile/)[^\s<>]+|"
    r"(?:https?://)?xhslink\.com/[^\s<>]+)",
    re.IGNORECASE,
)
_NOTE_ID_RE = re.compile(r"/(?:explore|item)/([0-9a-f]+)|/user/profile/[0-9a-f]+/([0-9a-f]+)", re.I)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
_MAGIC = (
    (0, b"\xff\xd8\xff", ".jpg"),
    (0, b"\x89PNG\r\n\x1a\n", ".png"),
    (8, b"WEBP", ".webp"),
    (4, b"ftypavif", ".avif"),
    (4, b"ftypheic", ".heic"),
    (4, b"ftypisom", ".mp4"),
    (4, b"ftypmp42", ".mp4"),
    (4, b"ftypMSNV", ".mp4"),
)


class _InitialStateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_script = False
        self._chunks: list[str] = []
        self.states: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "script":
            self._in_script = True
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._in_script:
            return
        text = "".join(self._chunks).strip()
        if text.startswith("window.__INITIAL_STATE__"):
            self.states.append(text)
        self._in_script = False
        self._chunks = []


def extract_xiaohongshu_url(text: str) -> str | None:
    matches = list(_URL_RE.finditer((text or "").strip()))
    if len(matches) != 1:
        return None
    value = matches[0].group(0).rstrip("，。！？、；：,.;:!?)]}>'\"")
    return value if "://" in value else f"https://{value}"


def validate_xiaohongshu_url(text: str) -> str:
    url = extract_xiaohongshu_url(text)
    if not url:
        raise ValueError("请粘贴且仅粘贴一个有效的小红书笔记链接或分享文本")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "xhslink.com" or host.endswith(".xhslink.com"):
        return url
    if not (host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")):
        raise ValueError("仅支持小红书笔记链接")
    if not _NOTE_ID_RE.search(parsed.path):
        raise ValueError("首版仅支持单篇小红书笔记，不支持主页、搜索或合集")
    return url


def load_xiaohongshu_cookies(path: str) -> dict[str, str]:
    if not path:
        return {}
    cookie_path = Path(path)
    if not cookie_path.exists():
        raise ValueError(f"小红书 Cookie 文件不存在：{cookie_path}")
    try:
        lines = cookie_path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError:
        try:
            lines = cookie_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ValueError("无法读取小红书 cookies.txt，请使用 UTF-8 Netscape 格式重新导出") from exc
    except OSError as exc:
        raise ValueError("无法读取小红书 cookies.txt") from exc
    result: dict[str, str] = {}
    for raw in lines:
        line = raw[len("#HttpOnly_") :] if raw.startswith("#HttpOnly_") else raw
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain, _include_subdomains, _cookie_path, _secure, _expires, name, value = fields
        if "xiaohongshu.com" in domain.lower() and name:
            result[name] = value
    if not result:
        raise ValueError("所选 cookies.txt 中没有找到小红书网站 Cookie，请重新导出")
    return result


def resolve_xiaohongshu_output_dir(
    request: XiaohongshuDownloadRequest, author: str = ""
) -> Path:
    result = request.output_dir
    if request.classify_by_platform:
        result /= "小红书"
    if request.classify_by_author:
        result /= sanitize_filename(author or "未知作者", 80)
    return result


def _replace_js_undefined(text: str) -> str:
    output: list[str] = []
    index = 0
    quote = ""
    escaped = False
    while index < len(text):
        char = text[index]
        if quote:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            output.append(char)
            index += 1
            continue
        if text.startswith("undefined", index):
            before = text[index - 1] if index else ""
            after = text[index + 9] if index + 9 < len(text) else ""
            if not (before.isalnum() or before in "_$" or after.isalnum() or after in "_$"):
                output.append("null")
                index += 9
                continue
        output.append(char)
        index += 1
    return "".join(output)


def parse_initial_state(html: str) -> dict[str, Any]:
    parser = _InitialStateParser()
    parser.feed(html)
    if not parser.states:
        raise ValueError("页面中没有找到小红书笔记数据，可能需要更新 Cookie 或通过验证")
    source = parser.states[-1].split("=", 1)[1].strip().rstrip(";")
    try:
        return json.loads(_replace_js_undefined(source))
    except (ValueError, TypeError) as exc:
        raise ValueError("小红书笔记数据格式已变化，暂时无法解析") from exc


def _deep_get(data: Any, *keys: Any) -> Any:
    try:
        for key in keys:
            if key == -1 and isinstance(data, dict):
                data = list(data.values())[-1]
            else:
                data = data[key]
        return data
    except (KeyError, IndexError, TypeError):
        return None


def extract_note_data(state: dict[str, Any]) -> dict[str, Any]:
    result = _deep_get(state, "noteData", "data", "noteData")
    if not isinstance(result, dict):
        result = _deep_get(state, "note", "noteDetailMap", -1, "note")
    if not isinstance(result, dict) or not result.get("noteId"):
        raise ValueError("没有取得有效笔记数据；请确认笔记可浏览并更新小红书 Cookie")
    return result


def _urls(*values: Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str):
            values2 = [value]
        elif isinstance(value, (list, tuple)):
            values2 = value
        else:
            continue
        for item in values2:
            if isinstance(item, str) and item and item not in result:
                result.append(item)
    return tuple(result)


def _image_token(url: str) -> str:
    parts = urlparse(url).path.lstrip("/").split("!", 1)[0].split("/")
    # Web image URLs commonly prefix the stable token with two expiring
    # signature path segments. CDN download URLs require only the stable tail.
    return "/".join(parts[2:] if len(parts) >= 3 else parts)


def image_url(source: str, image_format: str) -> str:
    token = _image_token(source)
    if not token:
        return source
    if image_format == "auto":
        return f"https://sns-img-bd.xhscdn.com/{token}"
    return f"https://ci.xiaohongshu.com/{token}?imageView2/format/{image_format}"


def select_video_asset(
    assets: list[XiaohongshuAsset], preference: str
) -> XiaohongshuAsset:
    if not assets:
        raise ValueError("该笔记没有可下载的视频资源")
    if any(asset.codec == "original" for asset in assets):
        return next(asset for asset in assets if asset.codec == "original")
    key = {
        "resolution": lambda item: (item.width or 0) * (item.height or 0),
        "bitrate": lambda item: item.bitrate or 0,
        "size": lambda item: -(item.size or 2**63),
    }.get(preference)
    if key is None:
        raise ValueError("无效的视频质量偏好")
    return max(assets, key=key)


class XiaohongshuService:
    def __init__(self) -> None:
        self._cancel = Event()

    def cancel(self) -> None:
        self._cancel.set()

    def _check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise ProcessCancelled("任务已取消")

    @staticmethod
    def _proxy_options(proxy: str | None) -> tuple[ProxyConnector | None, str | None]:
        if proxy and proxy.lower().startswith(("socks4://", "socks5://")):
            return ProxyConnector.from_url(proxy), None
        return None, proxy

    def analyze(
        self, request: XiaohongshuDownloadRequest, on_log: LogCallback | None = None
    ) -> XiaohongshuMediaInfo:
        self._cancel.clear()
        return asyncio.run(self._analyze(request, on_log or (lambda _text: None)))

    async def _analyze(
        self, request: XiaohongshuDownloadRequest, on_log: LogCallback
    ) -> XiaohongshuMediaInfo:
        url = validate_xiaohongshu_url(request.url)
        cookies = load_xiaohongshu_cookies(request.cookie_file)
        connector, request_proxy = self._proxy_options(request.proxy.url())
        headers = {"User-Agent": _USER_AGENT, "Referer": "https://www.xiaohongshu.com/explore"}
        timeout = aiohttp.ClientTimeout(total=request.timeout)
        try:
            async with aiohttp.ClientSession(
                connector=connector, cookies=cookies, headers=headers, timeout=timeout
            ) as session:
                self._check_cancelled()
                on_log("正在打开小红书笔记页面")
                async with session.get(url, proxy=request_proxy, allow_redirects=True) as response:
                    response.raise_for_status()
                    html = await response.text(errors="replace")
                    final_url = str(response.url)
                if "/404" in urlparse(final_url).path or "error_code=300031" in final_url:
                    raise ValueError("笔记暂时无法浏览；请确认链接有效，必要时在设置中更新小红书 Cookie")
                if any(marker in html for marker in ("安全验证", "verify", "captcha")) and "noteDetailMap" not in html:
                    raise ValueError("小红书触发安全验证；请先在浏览器完成验证并更新 Cookie")
                state = parse_initial_state(html)
                note = extract_note_data(state)
                return self._media_from_note(final_url, note, request.image_format)
        finally:
            if connector and not connector.closed:
                await connector.close()

    @staticmethod
    def _media_from_note(
        url: str, note: dict[str, Any], image_format: str = "auto"
    ) -> XiaohongshuMediaInfo:
        note_id = str(note.get("noteId") or "")
        title = str(note.get("title") or note.get("desc") or note_id or "小红书笔记")
        user = note.get("user") if isinstance(note.get("user"), dict) else {}
        images = note.get("imageList") if isinstance(note.get("imageList"), list) else []
        image_assets: list[XiaohongshuAsset] = []
        live_assets: list[XiaohongshuAsset] = []
        for index, item in enumerate(images, start=1):
            if not isinstance(item, dict):
                continue
            source = item.get("urlDefault") or item.get("url")
            if isinstance(source, str) and source:
                image_assets.append(
                    XiaohongshuAsset(
                        "image",
                        (image_url(source, image_format),),
                        index=index,
                        width=item.get("width"),
                        height=item.get("height"),
                        extension="" if image_format == "auto" else f".{image_format}",
                    )
                )
            live = _deep_get(item, "stream", "h264")
            if isinstance(live, list) and live and isinstance(live[0], dict):
                urls = _urls(live[0].get("masterUrl"), live[0].get("backupUrls"))
                if urls:
                    live_assets.append(XiaohongshuAsset("live_photo", urls, index=index, extension=".mp4"))

        video_assets: list[XiaohongshuAsset] = []
        origin_key = _deep_get(note, "video", "consumer", "originVideoKey")
        if isinstance(origin_key, str) and origin_key:
            video_assets.append(
                XiaohongshuAsset(
                    "video",
                    (f"https://sns-video-bd.xhscdn.com/{origin_key}",),
                    codec="original",
                    extension=".mp4",
                )
            )
        stream = _deep_get(note, "video", "media", "stream")
        if isinstance(stream, dict):
            for codec in ("h264", "h265"):
                items = stream.get(codec)
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    urls = _urls(item.get("backupUrls"), item.get("masterUrl"))
                    if urls:
                        video_assets.append(
                            XiaohongshuAsset(
                                "video", urls, width=item.get("width"), height=item.get("height"),
                                bitrate=item.get("videoBitrate"), size=item.get("size"), codec=codec,
                                extension=".mp4",
                            )
                        )
        media_type = "video" if note.get("type") == "video" and len(images) <= 1 else "gallery"
        timestamp = note.get("time")
        upload_date = ""
        if isinstance(timestamp, (int, float)):
            upload_date = datetime.fromtimestamp(timestamp / 1000).strftime("%Y%m%d")
        cover = image_assets[0] if image_assets else None
        return XiaohongshuMediaInfo(
            webpage_url=url,
            note_id=note_id,
            title=title,
            description=str(note.get("desc") or ""),
            author=str(user.get("nickname") or user.get("nickName") or ""),
            author_id=str(user.get("userId") or ""),
            upload_date=upload_date,
            thumbnail=cover.urls[0] if cover else "",
            media_type=media_type,
            video_assets=video_assets,
            image_assets=image_assets,
            live_assets=live_assets,
            cover_asset=cover,
        )

    def download(
        self,
        request: XiaohongshuDownloadRequest,
        on_progress: ProgressCallback,
        on_log: LogCallback | None = None,
    ) -> list[Path]:
        self._cancel.clear()
        return asyncio.run(self._download(request, on_progress, on_log or (lambda _text: None)))

    async def _download(
        self, request: XiaohongshuDownloadRequest, on_progress: ProgressCallback, on_log: LogCallback
    ) -> list[Path]:
        media = request.media or await self._analyze(request, on_log)
        output_dir = resolve_xiaohongshu_output_dir(request, media.author)
        output_dir.mkdir(parents=True, exist_ok=True)
        values = {
            "title": media.title,
            "id": media.note_id,
            "author": media.author,
            "channel": media.author,
            "platform": "小红书",
            "upload_date": media.upload_date,
            "type": "视频" if media.media_type == "video" else "图文",
        }
        stem = render_filename_template(request.filename_template, values)
        staging = output_dir / f".vdk-xhs-{media.note_id}-{time.time_ns()}"
        staging.mkdir()
        connector, request_proxy = self._proxy_options(request.proxy.url())
        headers = {"User-Agent": _USER_AGENT, "Referer": media.webpage_url}
        cookies = load_xiaohongshu_cookies(request.cookie_file)
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=request.timeout, sock_read=request.timeout)
        try:
            async with aiohttp.ClientSession(
                connector=connector, cookies=cookies, headers=headers, timeout=timeout
            ) as session:
                if media.media_type == "video":
                    asset = select_video_asset(media.video_assets, request.video_preference)
                    files = await self._download_video(
                        session, request_proxy, staging, stem, asset, media, request, on_progress, on_log
                    )
                    final: list[Path] = []
                    for path in files:
                        target = unique_path(output_dir / path.name)
                        path.replace(target)
                        final.append(target)
                    shutil.rmtree(staging, ignore_errors=True)
                    on_progress(TaskProgress("完成", 100, 100, message="小红书视频下载完成"))
                    return final
                return await self._download_gallery(
                    session, request_proxy, staging, output_dir, stem, media, on_progress, on_log
                )
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            if connector and not connector.closed:
                await connector.close()

    async def _download_video(
        self, session, proxy, staging, stem, asset, media, request, on_progress, on_log
    ) -> list[Path]:
        tasks: list[tuple[XiaohongshuAsset, str, bool]] = [(asset, stem, True)]
        if request.download_thumbnail and media.cover_asset:
            tasks.append((media.cover_asset, f"{stem}.cover", False))
        output: list[Path] = []
        for completed, (item, name, required) in enumerate(tasks):
            try:
                output.append(
                    await self._download_asset(session, proxy, item, staging, name, completed, len(tasks), on_progress, on_log)
                )
            except Exception as exc:
                if required:
                    raise
                on_log(f"封面下载失败，主视频仍然保留：{exc}")
        return output

    async def _download_gallery(
        self, session, proxy, staging, output_dir, stem, media, on_progress, on_log
    ) -> list[Path]:
        if not media.image_assets:
            raise ValueError("该笔记没有可下载的静态图片")
        tasks = [(item, f"{item.index:02d}", True) for item in media.image_assets]
        tasks += [(item, f"{item.index:02d}_live", False) for item in media.live_assets]
        for completed, (item, name, required) in enumerate(tasks):
            try:
                await self._download_asset(
                    session, proxy, item, staging, name, completed, len(tasks), on_progress, on_log
                )
            except Exception as exc:
                if required:
                    raise RuntimeError(f"第 {item.index} 张图片下载失败：{exc}") from exc
                on_log(f"第 {item.index} 个实况片段下载失败，静态图片仍然保留：{exc}")
        target = unique_path(output_dir / stem)
        staging.replace(target)
        files = sorted(path for path in target.iterdir() if path.is_file())
        on_progress(TaskProgress("完成", 100, 100, message="小红书图文下载完成"))
        return files

    async def _download_asset(
        self, session, proxy, asset, directory, name, completed, total, on_progress, on_log
    ) -> Path:
        part = directory / f"{name}.part"
        last_error: Exception | None = None
        for url in asset.urls:
            for attempt in range(1, 4):
                self._check_cancelled()
                offset = part.stat().st_size if part.exists() else 0
                headers = {"Range": f"bytes={offset}-"} if offset else {}
                try:
                    async with session.get(url, proxy=proxy, headers=headers) as response:
                        if response.status == 416:
                            part.unlink(missing_ok=True)
                            on_log(f"{name} 的续传缓存失效，正在从头下载")
                            continue
                        if offset and response.status == 200:
                            part.unlink(missing_ok=True)
                            offset = 0
                        response.raise_for_status()
                        length = response.content_length
                        expected = offset + length if length is not None else None
                        async with aiofiles.open(part, "ab") as handle:
                            downloaded = offset
                            async for chunk in response.content.iter_chunked(1024 * 1024):
                                self._check_cancelled()
                                await handle.write(chunk)
                                downloaded += len(chunk)
                                stage_percent = downloaded * 100 / expected if expected else None
                                fraction = min(1.0, downloaded / expected) if expected else 0.0
                                on_progress(
                                    TaskProgress(
                                        "下载", (completed + fraction) * 100 / total,
                                        stage_percent, stage_indeterminate=expected is None,
                                        current_item=name, downloaded_bytes=downloaded, total_bytes=expected,
                                    )
                                )
                    suffix = self._detect_suffix(part, asset.extension)
                    target = directory / f"{name}{suffix}"
                    part.replace(target)
                    on_log(f"下载完成：{target.name}")
                    return target
                except ProcessCancelled:
                    raise
                except Exception as exc:
                    last_error = exc
                    on_log(f"{name} 下载失败，第 {attempt} 次重试：{exc}")
        raise RuntimeError(str(last_error or "所有下载地址均不可用"))

    @staticmethod
    def _detect_suffix(path: Path, default: str = "") -> str:
        with path.open("rb") as handle:
            start = handle.read(16)
        for offset, signature, suffix in _MAGIC:
            if start[offset : offset + len(signature)] == signature:
                return suffix
        return default if default.startswith(".") else (f".{default}" if default else ".bin")
