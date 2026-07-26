from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote


@dataclass(slots=True)
class ProxyConfig:
    scheme: Literal["direct", "http", "https", "socks4", "socks5"] = "direct"
    host: str = ""
    port: int | None = None
    username: str = ""
    password: str = ""

    def url(self) -> str | None:
        if self.scheme == "direct":
            return None
        if not self.host or not self.port:
            raise ValueError("代理主机和端口不能为空")
        auth = ""
        if self.username:
            auth = quote(self.username, safe="")
            if self.password:
                auth += f":{quote(self.password, safe='')}"
            auth += "@"
        return f"{self.scheme}://{auth}{self.host}:{self.port}/"

    def persisted(self) -> dict[str, Any]:
        data = asdict(self)
        data["password"] = ""
        return data


@dataclass(slots=True)
class TranscodeConfig:
    enabled: bool = True
    keep_source: bool = False
    scale: str = "源尺寸"
    portrait: bool = False
    rotation: Literal["0", "90", "-90", "180"] = "0"
    mirror: bool = False
    force_display_aspect: bool = False
    no_upscale: bool = False
    scale_algorithm: Literal["bicubic", "bilinear", "lanczos", "neighbor"] = "lanczos"
    rate_mode: Literal["vbr", "cbr", "cq"] = "vbr"
    video_bitrate: str = "auto"
    maximum_bitrate: str = "auto"
    quality: int = 23
    target_size_mib: float | None = None
    size_locked: bool = False
    two_pass: bool = False
    highest_quality: bool = False
    audio_convert: bool = False
    audio_codec: Literal["copy", "aac", "mp3", "ac3", "none"] = "aac"
    audio_bitrate_kbps: int | None = 256
    audio_channels: Literal["source", "mono", "stereo", "5.1"] = "source"
    audio_sample_rate: int | None = 48000
    video_encoder: Literal["cpu", "nvidia", "intel", "amd"] = "cpu"
    hardware_decode: str = "auto"
    hardware_filter: str = "auto"
    source_video_bitrate_kbps: int | None = None
    source_video_codec: str = ""
    suffix_mode: Literal["auto", "custom", "none"] = "auto"
    custom_suffix: str = ""


@dataclass(slots=True)
class FormatInfo:
    format_id: str
    ext: str = ""
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    dynamic_range: str = ""
    vcodec: str = "none"
    acodec: str = "none"
    vbr: float | None = None
    abr: float | None = None
    tbr: float | None = None
    filesize: int | None = None
    filesize_approx: int | None = None
    format_note: str = ""
    protocol: str = ""

    @property
    def has_video(self) -> bool:
        return bool(self.vcodec and self.vcodec != "none")

    @property
    def has_audio(self) -> bool:
        return bool(self.acodec and self.acodec != "none")

    @property
    def size(self) -> int | None:
        return self.filesize or self.filesize_approx

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "FormatInfo":
        fields = cls.__dataclass_fields__
        return cls(**{key: data.get(key) for key in fields if key in data})


@dataclass(slots=True, frozen=True)
class SubtitleInfo:
    language: str
    name: str
    kind: Literal["manual", "automatic"]
    formats: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class SubtitleSelection:
    language: str
    kind: Literal["manual", "automatic"]


@dataclass(slots=True)
class MediaInfo:
    webpage_url: str
    title: str
    media_id: str
    extractor: str
    channel: str = ""
    upload_date: str = ""
    platform: str = "YouTube"
    duration: float | None = None
    thumbnail: str = ""
    is_live: bool = False
    subtitles: dict[str, Any] = field(default_factory=dict)
    automatic_captions: dict[str, Any] = field(default_factory=dict)
    formats: list[FormatInfo] = field(default_factory=list)

    @property
    def subtitle_options(self) -> list[SubtitleInfo]:
        options: list[SubtitleInfo] = []
        for kind, source in (("manual", self.subtitles), ("automatic", self.automatic_captions)):
            for language, entries in source.items():
                formats = tuple(dict.fromkeys(item.get("ext", "") for item in entries if item.get("ext")))
                name = next((item.get("name", "") for item in entries if item.get("name")), "") or language
                options.append(SubtitleInfo(language, name, kind, formats))
        return sorted(options, key=lambda item: (item.kind != "manual", item.language.lower()))

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "MediaInfo":
        extractor = data.get("extractor_key") or data.get("extractor") or ""
        extractor_lower = extractor.lower()
        if "youtube" in extractor_lower:
            platform = "YouTube"
        elif "bilibili" in extractor_lower:
            platform = "哔哩哔哩"
        elif "twitter" in extractor_lower or extractor_lower == "x":
            platform = "X"
        elif "instagram" in extractor_lower:
            platform = "Instagram"
        elif "tiktok" in extractor_lower:
            platform = "TikTok"
        else:
            platform = extractor
        return cls(
            webpage_url=data.get("webpage_url") or data.get("original_url") or "",
            title=data.get("title") or "未命名视频",
            media_id=str(data.get("id") or ""),
            extractor=extractor,
            channel=data.get("channel") or data.get("uploader") or "",
            upload_date=data.get("upload_date") or "",
            platform=platform,
            duration=data.get("duration"),
            thumbnail=data.get("thumbnail") or "",
            is_live=bool(data.get("is_live")),
            subtitles=data.get("subtitles") or {},
            automatic_captions=data.get("automatic_captions") or {},
            formats=[FormatInfo.from_json(item) for item in data.get("formats", [])],
        )


@dataclass(slots=True)
class DownloadRequest:
    url: str
    output_dir: Path
    media_title: str = ""
    media_id: str = ""
    media_channel: str = ""
    media_upload_date: str = ""
    media_platform: str = "YouTube"
    filename_template: str = "{title} [{id}]"
    classify_by_platform: bool = True
    mode: Literal["video_audio", "video_only", "audio", "cover", "advanced"] = "video_audio"
    quality_preset: str = "best"
    custom_height: int | None = None
    video_format_id: str | None = None
    audio_format_id: str | None = None
    audio_output: Literal["original", "aac", "m4a", "mp3"] = "original"
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    cookie_file: str = ""
    cookie_browser: Literal["", "chrome", "edge"] = ""
    timeout: int = 30
    download_thumbnail: bool = False
    download_subtitles: bool = False
    subtitle_languages: str = "zh-Hans,zh.*,en.*"
    use_automatic_subtitles: bool = False
    subtitle_selections: list[SubtitleSelection] = field(default_factory=list)
    subtitle_format: Literal["srt", "vtt"] = "srt"
    transcode: TranscodeConfig = field(default_factory=TranscodeConfig)


@dataclass(slots=True)
class TaskProgress:
    stage: str
    total_percent: float | None = None
    stage_percent: float | None = None
    stage_indeterminate: bool = False
    current_item: str = ""
    speed: str = ""
    eta: str = ""
    total: str = ""
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    message: str = ""


@dataclass(slots=True)
class TaskResult:
    success: bool
    message: str
    output_path: Path | None = None
    output_files: list[Path] = field(default_factory=list)
    error_category: str = ""

    @property
    def output_directory(self) -> Path | None:
        candidates = [*self.output_files]
        if self.output_path is not None and self.output_path not in candidates:
            candidates.append(self.output_path)
        for candidate in candidates:
            path = Path(candidate)
            return path if path.is_dir() else path.parent
        return None


@dataclass(slots=True)
class DownloadArtifacts:
    media_path: Path | None
    cover_paths: list[Path] = field(default_factory=list)
    subtitle_paths: list[Path] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class DouyinAsset:
    kind: Literal["video", "image", "live_photo", "cover"]
    urls: tuple[str, ...]
    index: int = 0
    width: int | None = None
    height: int | None = None
    bitrate: int | None = None
    codec: str = ""
    extension: str = ""
    watermarked: bool = False
    uri: str = ""


@dataclass(slots=True)
class DouyinMediaInfo:
    webpage_url: str
    media_id: str
    title: str
    author: str = ""
    upload_date: str = ""
    duration: float | None = None
    thumbnail: str = ""
    media_type: Literal["video", "gallery"] = "video"
    video_assets: list[DouyinAsset] = field(default_factory=list)
    gallery_assets: list[DouyinAsset] = field(default_factory=list)
    cover_asset: DouyinAsset | None = None


@dataclass(slots=True)
class DouyinDownloadRequest:
    url: str
    output_dir: Path
    download_engine: Literal["native", "yt_dlp"] = "native"
    quality: Literal["highest", "1080p", "720p", "540p", "lowest"] = "highest"
    filename_template: str = "{title} [{id}]"
    classify_by_platform: bool = True
    classify_by_author: bool = False
    cookie_file: str = ""
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    timeout: int = 30
    download_thumbnail: bool = False
    transcode: TranscodeConfig = field(
        default_factory=lambda: TranscodeConfig(enabled=False)
    )
    media: DouyinMediaInfo | None = None


@dataclass(slots=True, frozen=True)
class XiaohongshuAsset:
    kind: Literal["video", "image", "live_photo", "cover"]
    urls: tuple[str, ...]
    index: int = 0
    width: int | None = None
    height: int | None = None
    bitrate: int | None = None
    size: int | None = None
    codec: str = ""
    extension: str = ""


@dataclass(slots=True)
class XiaohongshuMediaInfo:
    webpage_url: str
    note_id: str
    title: str
    description: str = ""
    author: str = ""
    author_id: str = ""
    upload_date: str = ""
    thumbnail: str = ""
    media_type: Literal["video", "gallery"] = "video"
    video_assets: list[XiaohongshuAsset] = field(default_factory=list)
    image_assets: list[XiaohongshuAsset] = field(default_factory=list)
    live_assets: list[XiaohongshuAsset] = field(default_factory=list)
    cover_asset: XiaohongshuAsset | None = None


@dataclass(slots=True)
class XiaohongshuDownloadRequest:
    url: str
    output_dir: Path
    video_preference: Literal["resolution", "bitrate", "size"] = "resolution"
    image_format: Literal["auto", "jpeg", "png", "webp"] = "auto"
    filename_template: str = "{title} [{id}]"
    classify_by_platform: bool = True
    classify_by_author: bool = False
    cookie_file: str = ""
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    timeout: int = 30
    download_thumbnail: bool = False
    media: XiaohongshuMediaInfo | None = None


@dataclass(slots=True, frozen=True)
class BilibiliSubtitleInfo:
    language: str
    name: str
    url: str


@dataclass(slots=True, frozen=True)
class BilibiliStreamInfo:
    kind: Literal["video", "audio"]
    stream_id: int
    label: str
    codec: str = ""
    width: int | None = None
    height: int | None = None
    fps: str = ""
    bandwidth: int | None = None
    size: int | None = None
    dynamic_range: str = ""
    urls: tuple[str, ...] = ()


@dataclass(slots=True)
class BilibiliPartInfo:
    cid: int
    page: int
    title: str
    duration: float | None = None
    selected: bool = False
    video_streams: list[BilibiliStreamInfo] = field(default_factory=list)
    audio_streams: list[BilibiliStreamInfo] = field(default_factory=list)
    subtitles: list[BilibiliSubtitleInfo] = field(default_factory=list)


@dataclass(slots=True)
class BilibiliMediaInfo:
    webpage_url: str
    bvid: str
    aid: int
    title: str
    uploader: str = ""
    upload_date: str = ""
    thumbnail: str = ""
    description: str = ""
    parts: list[BilibiliPartInfo] = field(default_factory=list)


@dataclass(slots=True)
class BilibiliDownloadRequest:
    url: str
    output_dir: Path
    selected_pages: list[int] = field(default_factory=list)
    video_quality: int | None = None
    video_codec: str = "avc"
    audio_quality: int | None = None
    filename_template: str = "{title} P{page} {part_title} [{bvid}]"
    classify_by_platform: bool = True
    cookie_file: str = ""
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    timeout: int = 30
    download_cover: bool = False
    download_subtitles: bool = False
    selected_subtitles: list[str] = field(default_factory=list)
    download_danmaku: bool = False
    download_metadata: bool = False
    media: BilibiliMediaInfo | None = None
