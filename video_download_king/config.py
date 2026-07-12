from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ProxyConfig, TranscodeConfig
from .paths import app_root, settings_path


def _transcode_config(data: Any, *, enabled_default: bool = True) -> TranscodeConfig:
    values = data if isinstance(data, dict) else {}
    migrated = dict(values)
    old_mode = migrated.get("rate_mode")
    if old_mode in {"auto", "bitrate"}:
        migrated["rate_mode"] = "vbr"
        old_bitrate = migrated.get("video_bitrate_kbps")
        migrated["video_bitrate"] = str(old_bitrate) if old_bitrate else "auto"
    elif old_mode == "quality":
        migrated["rate_mode"] = "cq"
    if "video_encoder" not in migrated:
        processor = migrated.get("processor", "cpu")
        vendor = migrated.get("hardware_vendor", "nvidia")
        migrated["video_encoder"] = vendor if processor == "gpu" else "cpu"
    filtered = {
        key: value
        for key, value in migrated.items()
        if key in TranscodeConfig.__dataclass_fields__
    }
    filtered.setdefault("enabled", enabled_default)
    return TranscodeConfig(**filtered)


@dataclass(slots=True)
class AppSettings:
    save_path: str = "downloads"
    classify_by_platform: bool = True
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    cookie_file: str = ""
    cookie_browser: str = ""
    douyin_cookie_file: str = ""
    bilibili_cookie_file: str = ""
    douyin_classify_by_author: bool = False
    timeout: int = 30
    output_mode: str = "video_audio"
    filename_template: str = "{title} [{id}]"
    download_thumbnail: bool = False
    download_subtitles: bool = False
    subtitle_languages: str = "zh-Hans,zh.*,en.*"
    subtitle_format: str = "srt"
    show_all_automatic_subtitles: bool = False
    transcode: TranscodeConfig = field(default_factory=TranscodeConfig)

    @property
    def resolved_save_path(self) -> Path:
        path = Path(self.save_path)
        return path if path.is_absolute() else app_root() / path


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings_path()

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            mode = data.get("output_mode", "video_audio")
            if mode == "video":
                mode = "video_audio"
            transcode_data = data.get("transcode", {})
            return AppSettings(
                save_path=data.get("save_path", "downloads"),
                classify_by_platform=bool(data.get("classify_by_platform", True)),
                proxy=ProxyConfig(**data.get("proxy", {})),
                cookie_file=data.get("cookie_file", ""),
                cookie_browser=data.get("cookie_browser", ""),
                douyin_cookie_file=data.get("douyin_cookie_file", ""),
                bilibili_cookie_file=data.get("bilibili_cookie_file", ""),
                douyin_classify_by_author=bool(data.get("douyin_classify_by_author", False)),
                timeout=int(data.get("timeout", 30)),
                output_mode=mode,
                filename_template=data.get("filename_template", "{title} [{id}]"),
                download_thumbnail=bool(data.get("download_thumbnail", False)),
                download_subtitles=bool(data.get("download_subtitles", False)),
                subtitle_languages=data.get("subtitle_languages", "zh-Hans,zh.*,en.*"),
                subtitle_format=data.get("subtitle_format", "srt"),
                show_all_automatic_subtitles=bool(data.get("show_all_automatic_subtitles", False)),
                transcode=_transcode_config(transcode_data),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
            shutil.copy2(self.path, backup)
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = asdict(settings)
        payload["proxy"] = settings.proxy.persisted()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
