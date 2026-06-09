from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_download_king.config import AppSettings, SettingsStore
from video_download_king.formats import format_selector
from video_download_king.models import DownloadRequest, ProxyConfig
from video_download_king.platforms import detect_platform, validate_first_version_url
from video_download_king.utils import sanitize_filename, unique_media_stem, unique_path
from video_download_king.ytdlp import YtDlpService


def request(**kwargs) -> DownloadRequest:
    defaults = {"url": "https://youtu.be/abc", "output_dir": Path("downloads")}
    defaults.update(kwargs)
    return DownloadRequest(**defaults)


def test_proxy_urls_and_password_is_not_persisted() -> None:
    proxy = ProxyConfig("socks5", "127.0.0.1", 1080, "user name", "p@ss")
    assert proxy.url() == "socks5://user%20name:p%40ss@127.0.0.1:1080/"
    assert proxy.persisted()["password"] == ""
    assert ProxyConfig().url() is None


def test_proxy_requires_host_and_port() -> None:
    with pytest.raises(ValueError):
        ProxyConfig("http").url()


@pytest.mark.parametrize(
    ("preset", "fragment"),
    [
        ("best", "bestvideo"),
        ("1080p", "height<=?1080"),
        ("worst", "worstvideo"),
        ("custom", "height<=?900"),
    ],
)
def test_quality_presets(preset: str, fragment: str) -> None:
    assert fragment in format_selector(request(quality_preset=preset, custom_height=900))


def test_advanced_selector() -> None:
    assert format_selector(request(mode="advanced", video_format_id="137", audio_format_id="140")) == "137+140"
    assert format_selector(request(mode="advanced", video_format_id="22")) == "22"
    with pytest.raises(ValueError):
        format_selector(request(mode="advanced"))


def test_platform_scope() -> None:
    assert detect_platform("https://www.youtube.com/watch?v=x") == "YouTube"
    assert detect_platform("https://youtu.be/x") == "YouTube"
    with pytest.raises(ValueError):
        validate_first_version_url("https://example.com/video")


def test_filename_and_unique_path(tmp_path: Path) -> None:
    assert sanitize_filename('A<B>:"C"/D|?*') == "A_B___C__D___"
    existing = tmp_path / "video.mp4"
    existing.touch()
    assert unique_path(existing).name == "video (1).mp4"
    assert unique_media_stem(tmp_path, "video") == "video (1)"


def test_settings_round_trip_omits_password(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    settings = AppSettings(save_path="媒体", proxy=ProxyConfig("http", "localhost", 8080, "u", "secret"))
    store.save(settings)
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["proxy"]["password"] == ""
    loaded = store.load()
    assert loaded.save_path == "媒体"
    assert loaded.proxy.host == "localhost"


def test_corrupt_settings_are_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    settings = SettingsStore(path).load()
    assert settings.save_path == "downloads"
    assert list(tmp_path.glob("settings.json.corrupt-*"))


def test_command_uses_argument_array_and_credentials(tmp_path: Path) -> None:
    req = request(
        proxy=ProxyConfig("http", "127.0.0.1", 7890),
        cookie_file="cookies.txt",
        quality_preset="720p",
    )
    args = YtDlpService().build_download_args(req, tmp_path)
    assert "--proxy" in args
    assert "http://127.0.0.1:7890/" in args
    assert "--cookies" in args
    assert any("height<=?720" in item for item in args)
    assert isinstance(args, list)
