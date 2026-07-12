from __future__ import annotations

import hashlib
import html
import http.cookiejar
import json
import math
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Event, Lock
from typing import Callable

from .models import (
    BilibiliDownloadRequest,
    BilibiliMediaInfo,
    BilibiliPartInfo,
    BilibiliStreamInfo,
    BilibiliSubtitleInfo,
    TaskProgress,
)
from .paths import ffmpeg_path
from .processes import ProcessCancelled, ProcessRunner
from .utils import render_filename_template, unique_media_stem, unique_path


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[TaskProgress], None]
_URL_RE = re.compile(r"https?://[^\s<>]+|(?:www\.)?bilibili\.com/[^\s<>]+|b23\.tv/[^\s<>]+", re.I)
_BV_RE = re.compile(r"BV[0-9A-Za-z]+", re.I)
_AV_RE = re.compile(r"(?:^|/|\b)av(\d+)", re.I)
_MIXIN = (46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52)
_QUALITY = {127:"8K 超高清",126:"杜比视界",125:"HDR 真彩",120:"4K 超清",116:"1080P60",112:"1080P 高码率",80:"1080P",74:"720P60",64:"720P",32:"480P",16:"360P",6:"240P"}


def extract_bilibili_url(text: str) -> str | None:
    match = _URL_RE.search(text.strip())
    if not match:
        return None
    url = match.group(0).rstrip("，。；;、)）]】")
    return url if url.startswith("http") else f"https://{url}"


def parse_bilibili_identifier(url: str) -> tuple[str, str | int, int | None]:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    selected_page = int(query.get("p", ["0"])[0]) or None
    if match := _BV_RE.search(url):
        return "bvid", match.group(0), selected_page
    if match := _AV_RE.search(url):
        return "aid", int(match.group(1)), selected_page
    raise ValueError("无法从链接中识别 BV 号或 AV 号")


def sign_wbi(params: dict[str, object], img_key: str, sub_key: str, timestamp: int | None = None) -> dict[str, str]:
    source = img_key + sub_key
    if len(source) < 64:
        raise ValueError("B站 WBI 密钥无效")
    mixin = "".join(source[index] for index in _MIXIN)[:32]
    normalized = {key: "".join(ch for ch in str(value) if ch not in "!'()*") for key, value in params.items()}
    normalized["wts"] = str(timestamp if timestamp is not None else round(time.time()))
    query = urllib.parse.urlencode(sorted(normalized.items()))
    normalized["w_rid"] = hashlib.md5(f"{query}{mixin}".encode()).hexdigest()
    return normalized


def load_netscape_cookies(path: str) -> http.cookiejar.MozillaCookieJar:
    jar = http.cookiejar.MozillaCookieJar()
    if not path:
        return jar
    cookie_path = Path(path)
    if not cookie_path.is_file():
        raise ValueError(f"B站 Cookie 文件不存在：{cookie_path}")
    # MozillaCookieJar follows the Windows locale and fails on UTF-8 exports
    # containing non-ASCII cookies. Parse the Netscape rows explicitly and only
    # retain Bilibili domains needed by this engine.
    for raw_line in cookie_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        if line.startswith("#HttpOnly_"):
            line = line.removeprefix("#HttpOnly_")
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain, include_subdomains, cookie_path_value, secure, expires, name = fields[:6]
        value = "\t".join(fields[6:])
        if "bilibili.com" not in domain.lower() or not name:
            continue
        jar.set_cookie(http.cookiejar.Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain=domain, domain_specified=True,
            domain_initial_dot=domain.startswith("."), path=cookie_path_value or "/",
            path_specified=True, secure=secure.upper() == "TRUE",
            expires=int(expires) if expires.isdigit() and int(expires) > 0 else None,
            discard=not expires.isdigit() or int(expires) <= 0, comment=None,
            comment_url=None, rest={}, rfc2109=False,
        ))
    return jar


def select_video_stream(streams: list[BilibiliStreamInfo], quality: int | None, codec: str) -> BilibiliStreamInfo:
    if not streams:
        raise ValueError("该分P没有可用视频流")
    target = quality if quality is not None else max(item.stream_id for item in streams)
    qualities = sorted({item.stream_id for item in streams if item.stream_id <= target}, reverse=True)
    chosen_quality = qualities[0] if qualities else min(item.stream_id for item in streams)
    candidates = [item for item in streams if item.stream_id == chosen_quality]
    return next((item for item in candidates if codec.lower() in item.codec.lower()),
                next((item for item in candidates if "avc" in item.codec.lower()), candidates[0]))


def select_audio_stream(streams: list[BilibiliStreamInfo], quality: int | None) -> BilibiliStreamInfo:
    if not streams:
        raise ValueError("该分P没有可用音频流")
    target = quality if quality is not None else max(item.stream_id for item in streams)
    eligible = [item for item in streams if item.stream_id <= target]
    return max(eligible or streams, key=lambda item: item.stream_id)


class BilibiliService:
    def __init__(self) -> None:
        self._cancel = Event()
        self._runner = ProcessRunner()
        self._opener: urllib.request.OpenerDirector | None = None
        self._timeout = 30
        self._img_key = ""
        self._sub_key = ""

    def cancel(self) -> None:
        self._cancel.set()
        self._runner.cancel()

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise ProcessCancelled("任务已取消")

    def _prepare(self, request: BilibiliDownloadRequest) -> None:
        self._cancel.clear()
        self._timeout = request.timeout
        handlers: list[object] = [urllib.request.HTTPCookieProcessor(load_netscape_cookies(request.cookie_file))]
        if proxy := request.proxy.url():
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self._opener = urllib.request.build_opener(*handlers)

    @staticmethod
    def _headers(referer: str = "https://www.bilibili.com/") -> dict[str, str]:
        return {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136 Safari/537.36", "Referer":referer, "Accept":"*/*"}

    def _open(self, url: str, *, headers: dict[str, str] | None = None, method: str | None = None):
        self._check_cancel()
        assert self._opener is not None
        try:
            return self._opener.open(urllib.request.Request(url, headers=headers or self._headers(), method=method), timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 412:
                raise RuntimeError("Bilibili HTTP 412：请求被风控拒绝，请更新 B站 cookies.txt 或更换网络") from exc
            raise RuntimeError(f"Bilibili HTTP {exc.code}：{exc.reason}") from exc

    def _json(self, url: str, params: dict[str, object] | None = None) -> dict:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        with self._open(url) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("code") == -101 and (data.get("data") or {}).get("wbi_img"):
            return data["data"]
        if data.get("code") != 0:
            code, message = data.get("code"), data.get("message", "未知错误")
            hint = "，请更新 B站 cookies.txt" if code in {-101, -352, -400, -403, -412} else ""
            raise RuntimeError(f"Bilibili API {code}：{message}{hint}")
        return data.get("data") or {}

    def _bootstrap_wbi(self) -> None:
        nav = self._json("https://api.bilibili.com/x/web-interface/nav")
        wbi = nav.get("wbi_img") or {}
        self._img_key = Path(urllib.parse.urlparse(wbi.get("img_url", "")).path).stem
        self._sub_key = Path(urllib.parse.urlparse(wbi.get("sub_url", "")).path).stem
        if not self._img_key or not self._sub_key:
            raise RuntimeError("B站导航接口未返回 WBI 密钥")

    def _wbi_json(self, url: str, params: dict[str, object]) -> dict:
        return self._json(url, sign_wbi(params, self._img_key, self._sub_key))

    def analyze(self, request: BilibiliDownloadRequest, on_log: LogCallback | None = None) -> BilibiliMediaInfo:
        self._prepare(request)
        on_log = on_log or (lambda _text: None)
        raw_url = extract_bilibili_url(request.url)
        if not raw_url:
            raise ValueError("未找到有效的哔哩哔哩视频链接")
        if urllib.parse.urlparse(raw_url).hostname == "b23.tv":
            on_log("正在解析 b23.tv 短链接")
            with self._open(raw_url) as response:
                raw_url = response.geturl()
        key, value, selected_page = parse_bilibili_identifier(raw_url)
        self._bootstrap_wbi()
        on_log("正在读取 B站稿件和分P信息")
        info = self._wbi_json("https://api.bilibili.com/x/web-interface/wbi/view", {key:value})
        rights = info.get("rights") or {}
        if rights.get("is_stein_gate"):
            raise ValueError("首版不支持互动视频")
        parts = [BilibiliPartInfo(int(item["cid"]), int(item.get("page", index)), item.get("part") or f"P{index}", item.get("duration"), selected=(int(item.get("page", index)) == (selected_page or 1))) for index, item in enumerate(info.get("pages") or [], 1)]
        if not parts:
            raise RuntimeError("B站稿件未返回可下载分P")
        media = BilibiliMediaInfo(
            webpage_url=f"https://www.bilibili.com/video/{info.get('bvid')}", bvid=info.get("bvid", ""), aid=int(info.get("aid") or 0), title=info.get("title") or "未命名视频", uploader=(info.get("owner") or {}).get("name", ""), upload_date=datetime.fromtimestamp(int(info.get("pubdate") or 0)).strftime("%Y%m%d") if info.get("pubdate") else "", thumbnail=info.get("pic", ""), description=info.get("desc", ""), parts=parts,
        )
        self.populate_part(media, next(part for part in parts if part.selected), on_log)
        return media

    def populate_part(self, media: BilibiliMediaInfo, part: BilibiliPartInfo, on_log: LogCallback | None = None) -> None:
        if part.video_streams:
            return
        (on_log or (lambda _text: None))(f"正在读取 P{part.page} 可用音视频流")
        play = self._wbi_json("https://api.bilibili.com/x/player/wbi/playurl", {"bvid":media.bvid,"cid":part.cid,"fnval":4048,"fourk":1,"qn":127})
        dash = play.get("dash") or {}
        descriptions = {int(item.get("quality")): item.get("new_description") or item.get("display_desc") for item in play.get("support_formats") or []}
        for item in dash.get("video") or []:
            sid = int(item.get("id") or 0); codec = item.get("codecs", "")
            codec_name = "av1" if "av01" in codec else "hevc" if any(x in codec for x in ("hev", "hvc")) else "avc"
            urls = tuple(dict.fromkeys(filter(None, [item.get("baseUrl") or item.get("base_url"), *(item.get("backupUrl") or item.get("backup_url") or [])])))
            part.video_streams.append(BilibiliStreamInfo("video", sid, descriptions.get(sid) or _QUALITY.get(sid, str(sid)), codec_name, item.get("width"), item.get("height"), str(item.get("frameRate") or item.get("frame_rate") or ""), item.get("bandwidth"), dynamic_range={126:"Dolby Vision",125:"HDR"}.get(sid,""), urls=urls))
        audio_items = list(dash.get("audio") or [])
        if (dash.get("dolby") or {}).get("audio"):
            audio_items.extend((dash.get("dolby") or {}).get("audio") or [])
        if (dash.get("flac") or {}).get("audio"):
            audio_items.append((dash.get("flac") or {})["audio"])
        for item in audio_items:
            sid = int(item.get("id") or 0); urls = tuple(dict.fromkeys(filter(None, [item.get("baseUrl") or item.get("base_url"), *(item.get("backupUrl") or item.get("backup_url") or [])])))
            part.audio_streams.append(BilibiliStreamInfo("audio", sid, {30251:"Hi-Res",30250:"Dolby Atmos",30280:"192K",30232:"132K",30216:"64K"}.get(sid,str(sid)), item.get("codecs", ""), bandwidth=item.get("bandwidth"), urls=urls))
        player = self._wbi_json("https://api.bilibili.com/x/player/wbi/v2", {"bvid":media.bvid,"cid":part.cid})
        part.subtitles = [BilibiliSubtitleInfo(str(item.get("lan") or item.get("id")), item.get("lan_doc") or str(item.get("lan") or "字幕"), "https:" + item["subtitle_url"] if item.get("subtitle_url", "").startswith("//") else item.get("subtitle_url", "")) for item in (player.get("subtitle") or {}).get("subtitles") or []]

    def _remote_size(self, urls: tuple[str, ...], referer: str) -> tuple[str, int | None]:
        last_error: Exception | None = None
        for url in urls:
            try:
                with self._open(url, headers=self._headers(referer), method="HEAD") as response:
                    return url, int(response.headers.get("Content-Length") or 0) or None
            except Exception as exc:
                last_error = exc
        if last_error: raise last_error
        raise RuntimeError("B站流没有可用 CDN 地址")

    def _download_stream(self, stream: BilibiliStreamInfo, path: Path, referer: str, progress: Callable[[int,int|None],None]) -> None:
        url, size = self._remote_size(stream.urls, referer)
        if not size:
            self._download_sequential(stream.urls, path, referer, progress)
            return
        chunk_size = 4 * 1024 * 1024
        ranges = [(start, min(start + chunk_size, size)) for start in range(0, size, chunk_size)]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            handle.truncate(size)
        lock = Lock(); downloaded = 0
        def fetch(bounds: tuple[int,int]) -> int:
            nonlocal downloaded
            start, end = bounds
            range_unsupported = True
            for candidate in (url, *[item for item in stream.urls if item != url]):
                for attempt in range(3):
                    self._check_cancel()
                    try:
                        headers = self._headers(referer); headers["Range"] = f"bytes={start}-{end-1}"
                        with self._open(candidate, headers=headers) as response:
                            if response.status != 206:
                                raise RuntimeError("CDN 不支持 Range")
                            range_unsupported = False
                            data = response.read()
                        if len(data) != end-start:
                            raise RuntimeError(f"分片短读：预期 {end-start}，实际 {len(data)}")
                        with lock:
                            with path.open("r+b") as handle:
                                handle.seek(start); handle.write(data)
                            downloaded += len(data); progress(downloaded, size)
                        return len(data)
                    except ProcessCancelled: raise
                    except Exception:
                        if attempt == 2: break
                        time.sleep(0.35 * (attempt + 1))
            if range_unsupported:
                raise RuntimeError("CDN 不支持 Range")
            raise RuntimeError(f"B站分片下载失败：{start}-{end-1}")
        try:
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="bili-range") as pool:
                futures = [pool.submit(fetch, item) for item in ranges]
                for future in as_completed(futures): future.result()
        except RuntimeError as exc:
            if "不支持 Range" not in str(exc): raise
            path.unlink(missing_ok=True)
            self._download_sequential(stream.urls, path, referer, progress)
        if path.stat().st_size != size:
            raise RuntimeError("B站媒体流大小校验失败")

    def _download_sequential(self, urls: tuple[str,...], path: Path, referer: str, progress: Callable[[int,int|None],None]) -> None:
        last_error: Exception | None = None
        for url in urls:
            try:
                downloaded = 0
                with self._open(url, headers=self._headers(referer)) as response, path.open("wb") as handle:
                    total = int(response.headers.get("Content-Length") or 0) or None
                    while True:
                        self._check_cancel(); block = response.read(256 * 1024)
                        if not block: break
                        handle.write(block); downloaded += len(block); progress(downloaded, total)
                if total and downloaded != total: raise RuntimeError("顺序下载短读")
                return
            except ProcessCancelled: raise
            except Exception as exc: last_error = exc; path.unlink(missing_ok=True)
        raise RuntimeError(f"所有 B站 CDN 均下载失败：{last_error}")

    def download(self, request: BilibiliDownloadRequest, on_progress: ProgressCallback, on_log: LogCallback) -> list[Path]:
        self._prepare(request)
        self._bootstrap_wbi()
        media = request.media or self.analyze(request, on_log)
        selected = [part for part in media.parts if part.page in request.selected_pages]
        if not selected: raise ValueError("请至少选择一个分P")
        output_dir = request.output_dir / "哔哩哔哩" if request.classify_by_platform else request.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[Path] = []; warnings: list[str] = []; last_total = 0.0
        for part_index, part in enumerate(selected):
            self._check_cancel(); self.populate_part(media, part, on_log)
            video = select_video_stream(part.video_streams, request.video_quality, request.video_codec)
            audio = select_audio_stream(part.audio_streams, request.audio_quality)
            if video.stream_id != request.video_quality or request.video_codec not in video.codec:
                on_log(f"P{part.page} 使用回退视频流：{video.label} / {video.codec}")
            values = {"title":media.title,"id":media.bvid,"bvid":media.bvid,"aid":str(media.aid),"uploader":media.uploader,"author":media.uploader,"channel":media.uploader,"platform":"哔哩哔哩","upload_date":media.upload_date,"page":str(part.page),"part_title":part.title,"index":f"{part.page:02d}","type":"视频","asset":"视频"}
            stem = unique_media_stem(output_dir, render_filename_template(request.filename_template, values))
            staging = output_dir / f".vdk-bili-{media.bvid}-{part.cid}-{time.time_ns()}"; staging.mkdir()
            try:
                video_path, audio_path = staging / "video.m4s", staging / "audio.m4s"
                def report(stage: str, offset: float, span: float):
                    def callback(done: int, total: int | None):
                        nonlocal last_total
                        stage_pct = done * 100 / total if total else None
                        local = offset + span * ((stage_pct or 0) / 100)
                        overall = (part_index + local / 100) * 100 / len(selected)
                        last_total = max(last_total, overall)
                        on_progress(TaskProgress(stage,last_total,stage_pct,stage_indeterminate=total is None,current_item=f"P{part.page} {part.title}",downloaded_bytes=done,total_bytes=total))
                    return callback
                on_log(f"下载 P{part.page} 视频流：{video.label} / {video.codec}")
                self._download_stream(video, video_path, media.webpage_url, report("下载视频",0,42))
                on_log(f"下载 P{part.page} 音频流：{audio.label}")
                self._download_stream(audio, audio_path, media.webpage_url, report("下载音频",42,38))
                temp_output = staging / "merged.mp4"
                on_progress(TaskProgress("合并音视频", max(last_total,(part_index+.8)*100/len(selected)), None, True, f"P{part.page} {part.title}"))
                code, output = self._runner.run([ffmpeg_path(),"-y","-i",video_path,"-i",audio_path,"-map","0:v:0","-map","1:a:0","-c","copy","-movflags","+faststart",temp_output], cwd=staging, capture=True)
                if code or not temp_output.is_file() or temp_output.stat().st_size == 0:
                    raise RuntimeError(f"FFmpeg 无转码合并失败：{output[-1200:]}")
                final = unique_path(output_dir / f"{stem}.mp4"); temp_output.replace(final); results.append(final)
                for label, enabled, action in (("封面",request.download_cover,lambda:self._save_cover(media,output_dir,stem)),("字幕",request.download_subtitles,lambda:self._save_subtitles(part,request,output_dir,stem)),("弹幕",request.download_danmaku,lambda:self._save_danmaku(part,media,output_dir,stem)),("元数据",request.download_metadata,lambda:self._save_nfo(media,part,output_dir,stem))):
                    if enabled:
                        try: results.extend(action())
                        except Exception as exc: warnings.append(f"P{part.page} {label}失败：{exc}"); on_log(warnings[-1])
            except Exception:
                failed_dir = output_dir / f"{stem}.failed-parts"
                if staging.exists():
                    failed_dir = unique_path(failed_dir); staging.replace(failed_dir)
                raise
            finally:
                if staging.exists(): shutil.rmtree(staging, ignore_errors=True)
        on_progress(TaskProgress("完成",100,100,message="；".join(warnings)))
        return results

    def _download_bytes(self, url: str, referer: str) -> bytes:
        with self._open(url, headers=self._headers(referer)) as response: return response.read()

    def _save_cover(self, media, directory, stem) -> list[Path]:
        path = unique_path(directory / f"{stem}.jpg"); path.write_bytes(self._download_bytes(media.thumbnail,media.webpage_url)); return [path]

    def _save_subtitles(self, part, request, directory, stem) -> list[Path]:
        paths=[]
        for sub in part.subtitles:
            if request.selected_subtitles and sub.language not in request.selected_subtitles: continue
            body=json.loads(self._download_bytes(sub.url,"https://www.bilibili.com/").decode("utf-8")).get("body") or []
            lines=[]
            for index,item in enumerate(body,1): lines.extend([str(index),f"{_srt_time(item['from'])} --> {_srt_time(item['to'])}",item.get("content","").strip(),""])
            path=unique_path(directory/f"{stem}.{sub.language}.srt"); path.write_text("\n".join(lines),encoding="utf-8-sig"); paths.append(path)
        return paths

    def _save_danmaku(self, part, media, directory, stem) -> list[Path]:
        root=ET.fromstring(self._download_bytes(f"https://comment.bilibili.com/{part.cid}.xml",media.webpage_url))
        events=[]
        for node in root.findall("d"):
            values=(node.get("p") or "").split(","); start=float(values[0] or 0); text=_ass_escape(node.text or "")
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(start+6)},Default,,0,0,0,,{text}")
        header="[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Microsoft YaHei,36,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,0,8,20,20,20,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        path=unique_path(directory/f"{stem}.danmaku.ass"); path.write_text(header+"\n".join(events),encoding="utf-8-sig"); return [path]

    def _save_nfo(self, media, part, directory, stem) -> list[Path]:
        path=unique_path(directory/f"{stem}.nfo"); path.write_text(f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<movie><title>{html.escape(media.title)}</title><originaltitle>{html.escape(part.title)}</originaltitle><plot>{html.escape(media.description)}</plot><studio>{html.escape(media.uploader)}</studio><uniqueid type=\"bilibili\" default=\"true\">{media.bvid}</uniqueid><aired>{media.upload_date}</aired><thumb>{html.escape(media.thumbnail)}</thumb></movie>\n",encoding="utf-8"); return [path]


def _srt_time(value: float) -> str:
    millis=round(float(value)*1000); hours,millis=divmod(millis,3600000); minutes,millis=divmod(millis,60000); seconds,millis=divmod(millis,1000); return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

def _ass_time(value: float) -> str:
    centis=max(0,round(value*100)); hours,centis=divmod(centis,360000); minutes,centis=divmod(centis,6000); seconds,centis=divmod(centis,100); return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"

def _ass_escape(value: str) -> str:
    return value.replace("\\","\\\\").replace("{","\\{").replace("}","\\}").replace("\n","\\N")
