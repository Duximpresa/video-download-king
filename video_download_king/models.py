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
    rate_mode: Literal["auto", "quality", "bitrate"] = "auto"
    quality: int = 23
    video_bitrate_kbps: int | None = None
    audio_bitrate_kbps: int | None = None


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


@dataclass(slots=True)
class MediaInfo:
    webpage_url: str
    title: str
    media_id: str
    extractor: str
    duration: float | None = None
    thumbnail: str = ""
    is_live: bool = False
    formats: list[FormatInfo] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "MediaInfo":
        return cls(
            webpage_url=data.get("webpage_url") or data.get("original_url") or "",
            title=data.get("title") or "未命名视频",
            media_id=str(data.get("id") or ""),
            extractor=data.get("extractor_key") or data.get("extractor") or "",
            duration=data.get("duration"),
            thumbnail=data.get("thumbnail") or "",
            is_live=bool(data.get("is_live")),
            formats=[FormatInfo.from_json(item) for item in data.get("formats", [])],
        )


@dataclass(slots=True)
class DownloadRequest:
    url: str
    output_dir: Path
    media_title: str = ""
    media_id: str = ""
    classify_by_platform: bool = True
    mode: Literal["video", "audio", "advanced"] = "video"
    quality_preset: str = "best"
    custom_height: int | None = None
    video_format_id: str | None = None
    audio_format_id: str | None = None
    audio_output: Literal["original", "aac", "m4a", "mp3"] = "original"
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    cookie_file: str = ""
    cookie_browser: Literal["", "chrome", "edge"] = ""
    timeout: int = 30
    transcode: TranscodeConfig = field(default_factory=TranscodeConfig)


@dataclass(slots=True)
class TaskProgress:
    stage: str
    percent: float | None = None
    speed: str = ""
    eta: str = ""
    total: str = ""
    message: str = ""


@dataclass(slots=True)
class TaskResult:
    success: bool
    message: str
    output_path: Path | None = None
    error_category: str = ""
