from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_download_king.config import AppSettings, SettingsStore
from video_download_king.errors import categorize_error, user_facing_error
from video_download_king.formats import format_selector
from video_download_king.models import (
    DownloadArtifacts,
    DownloadRequest,
    MediaInfo,
    ProxyConfig,
    SubtitleSelection,
    TaskResult,
    TranscodeConfig,
)
from video_download_king.network_test import validate_test_url
from video_download_king.platforms import (
    detect_platform,
    proxy_recommended_platform,
    validate_first_version_url,
)
from video_download_king.utils import (
    render_filename_template,
    has_matching_language,
    sanitize_filename,
    sanitize_suffix,
    unique_media_stem,
    unique_path,
)
from video_download_king.ytdlp import DownloadProgressTracker, PROGRESS_RE, YtDlpService
from video_download_king.workers import DownloadWorker


def request(**kwargs) -> DownloadRequest:
    defaults = {"url": "https://youtu.be/abc", "output_dir": Path("downloads")}
    defaults.update(kwargs)
    return DownloadRequest(**defaults)


class JsonRunner:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.commands: list[list[str]] = []

    def run(self, args, **kwargs) -> tuple[int, str]:
        self.commands.append([str(item) for item in args])
        return 0, json.dumps(self.payload)

    def cancel(self) -> None:
        pass


def test_proxy_urls_and_password_is_not_persisted() -> None:
    proxy = ProxyConfig("socks5", "127.0.0.1", 1080, "user name", "p@ss")
    assert proxy.url() == "socks5://user%20name:p%40ss@127.0.0.1:1080/"
    assert proxy.persisted()["password"] == ""
    assert ProxyConfig().url() is None


def test_proxy_requires_host_and_port() -> None:
    with pytest.raises(ValueError):
        ProxyConfig("http").url()


def test_task_result_output_directory(tmp_path: Path) -> None:
    primary = tmp_path / "Instagram" / "video.mp4"
    sidecar = tmp_path / "Instagram" / "video.jpg"
    fallback = tmp_path / "other" / "fallback.mp4"
    primary.parent.mkdir()
    primary.touch()
    sidecar.touch()

    assert TaskResult(True, "完成", fallback, [primary, sidecar]).output_directory == primary.parent
    assert TaskResult(True, "完成", fallback, []).output_directory == fallback.parent
    assert TaskResult(True, "完成").output_directory is None

    directory_result = tmp_path / "gallery"
    directory_result.mkdir()
    assert TaskResult(True, "完成", directory_result).output_directory == directory_result


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


def test_video_only_selector() -> None:
    assert format_selector(request(mode="video_only", quality_preset="best")) == "bestvideo"
    assert "bestaudio" not in format_selector(request(mode="video_only", quality_preset="1080p"))
    args = YtDlpService().build_download_args(
        request(mode="video_only", audio_output="mp3"),
        Path("downloads"),
    )
    assert "--extract-audio" not in args


def test_platform_scope() -> None:
    assert detect_platform("https://www.youtube.com/watch?v=x") == "YouTube"
    assert detect_platform("https://youtu.be/x") == "YouTube"
    assert detect_platform("https://www.bilibili.com/video/BV1xx411c7mD") == "哔哩哔哩"
    assert detect_platform("https://b23.tv/example") == "哔哩哔哩"
    assert detect_platform("https://x.com/openai/status/123456") == "X"
    assert detect_platform("https://twitter.com/openai/status/123456") == "X"
    assert detect_platform("https://www.instagram.com/reel/ABC_123-/") == "Instagram"
    assert detect_platform("https://www.tiktok.com/@creator/video/1234567890") == "TikTok"
    assert detect_platform("https://vm.tiktok.com/ZMExample/") == "TikTok"
    assert validate_first_version_url("https://www.bilibili.com/video/BV1xx411c7mD") == "哔哩哔哩"
    assert validate_first_version_url("https://x.com/openai/status/123456") == "X"
    assert validate_first_version_url("https://x.com/bytopux/status/2076210959723466833/video/1") == "X"
    assert validate_first_version_url("https://twitter.com/openai/status/123456/video/2") == "X"
    with pytest.raises(ValueError, match="单条帖子或帖子内视频"):
        validate_first_version_url("https://x.com/openai")
    with pytest.raises(ValueError, match="单条帖子或帖子内视频"):
        validate_first_version_url("https://x.com/search?q=video")
    with pytest.raises(ValueError, match="单条帖子或帖子内视频"):
        validate_first_version_url("https://x.com/i/spaces/123456")
    with pytest.raises(ValueError):
        validate_first_version_url("https://example.com/video")


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/reel/ABC_123-/",
        "https://instagram.com/reels/ABC_123-/?utm_source=copy_link",
        "https://www.instagram.com/p/ABC_123-/",
        "https://www.instagram.com/tv/ABC_123-/",
        "https://www.instagram.com/example.user/reel/ABC_123-/",
        "instagram.com/p/ABC_123-",
    ],
)
def test_instagram_single_video_urls_are_supported(url: str) -> None:
    assert validate_first_version_url(url) == "Instagram"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/example.user/",
        "https://www.instagram.com/stories/example.user/123/",
        "https://www.instagram.com/explore/tags/video/",
        "https://www.instagram.com/live/123/",
        "https://www.instagram.com/reels/audio/123/",
        "https://www.instagram.com/share/reel/ABC_123-/",
        "https://www.instagram.com/p/",
    ],
)
def test_instagram_non_single_video_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="仅支持单个 Reel、视频帖子或 IGTV"):
        validate_first_version_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/@creator.name/video/1234567890",
        "https://tiktok.com/@creator_name/video/1234567890?is_from_webapp=1",
        "tiktok.com/@creator-name/video/1234567890",
        "https://vm.tiktok.com/ZMExample/",
        "https://vt.tiktok.com/ZSExample/",
        "https://www.tiktok.com/t/ZTExample/",
    ],
)
def test_tiktok_single_video_urls_are_supported(url: str) -> None:
    assert validate_first_version_url(url) == "TikTok"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/@creator.name",
        "https://www.tiktok.com/@creator.name/photo/1234567890",
        "https://www.tiktok.com/@creator.name/live",
        "https://www.tiktok.com/@creator.name/collection/favorites-1234567890",
        "https://www.tiktok.com/music/example-1234567890",
        "https://www.tiktok.com/tag/example",
        "https://m.tiktok.com/v/1234567890.html",
    ],
)
def test_tiktok_non_single_video_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="仅支持单个视频长链或分享短链"):
        validate_first_version_url(url)


def test_bilibili_media_info_uses_chinese_platform_name() -> None:
    media = MediaInfo.from_json(
        {
            "extractor_key": "BiliBili",
            "webpage_url": "https://www.bilibili.com/video/BV1xx411c7mD",
            "title": "测试视频",
            "id": "BV1xx411c7mD",
        }
    )
    assert media.platform == "哔哩哔哩"


def test_twitter_media_info_uses_x_platform_name() -> None:
    media = MediaInfo.from_json(
        {
            "extractor_key": "Twitter",
            "webpage_url": "https://x.com/user/status/123",
            "title": "测试帖子",
            "id": "123",
        }
    )
    assert media.platform == "X"


def test_instagram_media_info_uses_platform_name() -> None:
    media = MediaInfo.from_json(
        {
            "extractor_key": "Instagram",
            "webpage_url": "https://www.instagram.com/reel/ABC_123-/",
            "title": "测试 Reel",
            "id": "ABC_123-",
        }
    )
    assert media.platform == "Instagram"


def test_tiktok_media_info_uses_platform_name() -> None:
    media = MediaInfo.from_json(
        {
            "extractor_key": "TikTok",
            "webpage_url": "https://www.tiktok.com/@creator/video/1234567890",
            "title": "测试 TikTok",
            "id": "1234567890",
        }
    )
    assert media.platform == "TikTok"


def test_instagram_analysis_reuses_common_cookie() -> None:
    runner = JsonRunner(
        {
            "extractor_key": "Instagram",
            "webpage_url": "https://www.instagram.com/reel/ABC_123-/",
            "title": "测试 Reel",
            "id": "ABC_123-",
        }
    )
    media = YtDlpService(runner).analyze(
        "https://www.instagram.com/reel/ABC_123-/",
        cookie_file="common.txt",
    )
    assert media.platform == "Instagram"
    assert "--cookies" in runner.commands[0]
    assert "common.txt" in runner.commands[0]


def test_instagram_carousel_analysis_is_rejected() -> None:
    runner = JsonRunner(
        {
            "_type": "playlist",
            "extractor_key": "Instagram",
            "id": "ABC_123-",
            "entries": [{"id": "one"}, {"id": "two"}],
        }
    )
    with pytest.raises(ValueError, match="轮播或多视频帖子.*仅支持单个视频"):
        YtDlpService(runner).analyze("https://www.instagram.com/p/ABC_123-/")


def test_tiktok_short_link_analysis_reuses_common_cookie() -> None:
    runner = JsonRunner(
        {
            "_type": "video",
            "extractor_key": "TikTok",
            "webpage_url": "https://www.tiktok.com/@/video/1234567890",
            "title": "测试 TikTok",
            "id": "1234567890",
            "formats": [{"format_id": "h264", "vcodec": "h264", "acodec": "aac"}],
        }
    )
    media = YtDlpService(runner).analyze(
        "https://vm.tiktok.com/ZMExample/",
        cookie_file="common.txt",
    )
    assert media.platform == "TikTok"
    assert "--cookies" in runner.commands[0]
    assert "common.txt" in runner.commands[0]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "_type": "playlist",
            "extractor_key": "TikTok",
            "webpage_url": "https://www.tiktok.com/@creator/video/1234567890",
            "entries": [{"id": "one"}, {"id": "two"}],
            "formats": [{"vcodec": "h264"}],
        },
        {
            "_type": "video",
            "extractor_key": "TikTok",
            "webpage_url": "https://www.tiktok.com/@creator/photo/1234567890",
            "formats": [{"vcodec": "h264"}],
        },
        {
            "_type": "video",
            "extractor_key": "TikTok",
            "webpage_url": "https://www.tiktok.com/@creator/video/1234567890",
            "formats": [],
        },
    ],
)
def test_tiktok_short_link_must_resolve_to_one_video(payload: dict) -> None:
    with pytest.raises(ValueError, match="仅支持单个视频.*不支持图片"):
        YtDlpService(JsonRunner(payload)).analyze("https://vt.tiktok.com/ZSExample/")


def test_instagram_download_uses_platform_directory(tmp_path: Path) -> None:
    class StubDownloader:
        def __init__(self) -> None:
            self.output_dir: Path | None = None

        def download(self, download_request, output_dir, on_progress, on_log) -> DownloadArtifacts:
            self.output_dir = output_dir
            output_dir.mkdir(parents=True)
            media_path = output_dir / "video.mp4"
            media_path.touch()
            return DownloadArtifacts(media_path)

        def cancel(self) -> None:
            pass

    worker = DownloadWorker(
        request(
            url="https://www.instagram.com/reel/ABC_123-/",
            output_dir=tmp_path,
            mode="video_only",
            media_platform="Instagram",
        )
    )
    downloader = StubDownloader()
    worker.downloader = downloader
    results = []
    worker.completed.connect(results.append)
    worker.run()
    assert downloader.output_dir == tmp_path / "Instagram"
    assert results and results[0].success


def test_tiktok_download_uses_platform_directory(tmp_path: Path) -> None:
    class StubDownloader:
        def __init__(self) -> None:
            self.output_dir: Path | None = None

        def download(self, download_request, output_dir, on_progress, on_log) -> DownloadArtifacts:
            self.output_dir = output_dir
            output_dir.mkdir(parents=True)
            media_path = output_dir / "video.mp4"
            media_path.touch()
            return DownloadArtifacts(media_path)

        def cancel(self) -> None:
            pass

    worker = DownloadWorker(
        request(
            url="https://www.tiktok.com/@creator/video/1234567890",
            output_dir=tmp_path,
            mode="video_only",
            media_platform="TikTok",
        )
    )
    downloader = StubDownloader()
    worker.downloader = downloader
    results = []
    worker.completed.connect(results.append)
    worker.run()
    assert downloader.output_dir == tmp_path / "TikTok"
    assert results and results[0].success


def test_bilibili_412_has_actionable_cookie_guidance() -> None:
    error = "ERROR: [BiliBili] HTTP Error 412: Precondition Failed"
    assert categorize_error(error) == "Cookie/风控"
    message = user_facing_error(error)
    assert "设置 > 网站登录" in message
    assert "完全退出浏览器" in message


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.youtube.com/watch?v=x", "YouTube"),
        ("youtu.be/x", "YouTube"),
        ("https://www.instagram.com/reel/x/", "Instagram"),
        ("https://www.tiktok.com/@creator/video/1", "TikTok"),
        ("https://vm.tiktok.com/ZMExample/", "TikTok"),
        ("https://x.com/user/status/1", "X"),
        ("https://twitter.com/user/status/1", "X"),
    ],
)
def test_proxy_recommendation_for_common_overseas_platforms(
    url: str, platform: str
) -> None:
    assert proxy_recommended_platform(url) == platform
    assert proxy_recommended_platform("https://www.douyin.com/video/1") is None


def test_connectivity_test_url_validation() -> None:
    assert validate_test_url("https://www.google.com/") == "https://www.google.com/"
    with pytest.raises(ValueError):
        validate_test_url("google.com")


def test_filename_and_unique_path(tmp_path: Path) -> None:
    assert sanitize_filename('A<B>:"C"/D|?*') == "A_B___C__D___"
    existing = tmp_path / "video.mp4"
    existing.touch()
    assert unique_path(existing).name == "video (1).mp4"
    assert unique_media_stem(tmp_path, "video") == "video (1)"
    assert (
        render_filename_template(
            "{title} [{id}] - {channel} - {upload_date}",
            {"title": "测试", "id": "abc", "channel": "频道", "upload_date": "20260102"},
        )
        == "测试 [abc] - 频道 - 2026-01-02"
    )
    assert (
        render_filename_template(
            "{title}-{author}-{type}-{index}-{asset}",
            {"title": "抖音", "channel": "作者", "type": "图集", "index": "03", "asset": "图片"},
        )
        == "抖音-作者-图集-03-图片"
    )
    with pytest.raises(ValueError):
        render_filename_template("{unknown}", {})
    assert sanitize_suffix("兼容:版") == "_兼容_版"
    assert has_matching_language({"en", "ja"}, "zh.*,en.*")
    assert not has_matching_language({"ja"}, "zh.*,en.*")


def test_settings_round_trip_omits_password(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    settings = AppSettings(
        save_path="媒体",
        proxy=ProxyConfig("http", "localhost", 8080, "u", "secret"),
        subtitle_format="vtt",
        show_all_automatic_subtitles=True,
    )
    store.save(settings)
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["proxy"]["password"] == ""
    loaded = store.load()
    assert loaded.save_path == "媒体"
    assert loaded.proxy.host == "localhost"
    assert loaded.subtitle_format == "vtt"
    assert loaded.show_all_automatic_subtitles


def test_old_douyin_transcode_settings_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "transcode": {"enabled": True, "quality": 18},
                "douyin_transcode": {"enabled": True, "quality": 5},
            }
        ),
        encoding="utf-8",
    )
    settings = SettingsStore(path).load()
    assert settings.transcode.enabled
    assert settings.transcode.quality == 18
    assert not hasattr(settings, "douyin_transcode")


def test_old_transcode_rate_and_hardware_settings_are_migrated(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "transcode": {
                    "rate_mode": "bitrate",
                    "video_bitrate_kbps": 6000,
                    "processor": "gpu",
                    "hardware_vendor": "intel",
                    "audio_bitrate_kbps": 192,
                }
            }
        ),
        encoding="utf-8",
    )
    config = SettingsStore(path).load().transcode
    assert config.rate_mode == "vbr"
    assert config.video_bitrate == "6000"
    assert config.video_encoder == "intel"
    assert config.audio_bitrate_kbps == 192


def test_old_video_mode_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"output_mode": "video"}), encoding="utf-8")
    assert SettingsStore(path).load().output_mode == "video_audio"


def test_old_subtitle_settings_load_without_preselection(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"download_subtitles": True, "subtitle_languages": "zh.*,en.*"}),
        encoding="utf-8",
    )
    settings = SettingsStore(path).load()
    assert settings.download_subtitles
    assert settings.subtitle_format == "srt"


def test_old_embed_thumbnail_setting_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"embed_thumbnail": True}), encoding="utf-8")
    settings = SettingsStore(path).load()
    assert not hasattr(settings, "embed_thumbnail")


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


def test_download_options_for_sidecars_and_naming(tmp_path: Path) -> None:
    req = request(
        media_title="标题",
        media_id="abc",
        media_channel="频道",
        filename_template="{title}-{channel}-{id}",
        download_thumbnail=True,
        subtitle_selections=[SubtitleSelection("en", "manual"), SubtitleSelection("zh-Hans", "automatic")],
        subtitle_format="srt",
    )
    args = YtDlpService().build_download_args(req, tmp_path)
    assert "--write-thumbnail" in args
    assert "--progress" in args
    assert any("标题-频道-abc" in item for item in args)
    commands = YtDlpService.build_subtitle_commands(req, str(tmp_path / "video.%(ext)s"))
    assert len(commands) == 2
    manual = commands[0][1]
    automatic = commands[1][1]
    assert "--write-subs" in manual and "en" in manual
    assert "--write-auto-subs" in automatic and "zh-Hans" in automatic
    assert "--convert-subs" in manual and "--convert-subs" in automatic


def test_vtt_subtitle_command_does_not_convert(tmp_path: Path) -> None:
    req = request(
        subtitle_selections=[SubtitleSelection("ja", "manual")],
        subtitle_format="vtt",
    )
    command = YtDlpService.build_subtitle_commands(req, str(tmp_path / "video.%(ext)s"))[0][1]
    assert "--sub-format" in command
    assert "vtt/best" in command
    assert "--convert-subs" not in command


def test_subtitle_options_are_grouped() -> None:
    media = MediaInfo.from_json(
        {
            "id": "x",
            "title": "x",
            "subtitles": {"en": [{"ext": "vtt", "name": "English"}]},
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
                "zh-Hans": [{"ext": "vtt", "name": "Chinese (Simplified)"}],
            },
        }
    )
    assert [(item.language, item.kind) for item in media.subtitle_options] == [
        ("en", "manual"),
        ("en", "automatic"),
        ("zh-Hans", "automatic"),
    ]


def test_download_progress_tracks_two_streams_without_going_backwards() -> None:
    tracker = DownloadProgressTracker(expected_streams=2)
    lines = [
        "__VDK_PROGRESS__100.0%|1MiB/s|00:00|10MiB|100|100|NA|137",
        "__VDK_PROGRESS__ 10.0%|1MiB/s|00:09|5MiB|10|100|NA|140",
        "__VDK_PROGRESS__100.0%|1MiB/s|00:00|5MiB|100|100|NA|140",
    ]
    progress = [tracker.update(PROGRESS_RE.match(line)) for line in lines]
    totals = [item.total_percent for item in progress]
    assert totals == sorted(totals)
    assert totals[-1] == 100
    assert progress[1].stage_percent == 10
    assert progress[1].current_item == "格式 140"


def test_download_progress_handles_unknown_total() -> None:
    tracker = DownloadProgressTracker(expected_streams=1)
    progress = tracker.update(
        PROGRESS_RE.match("__VDK_PROGRESS__ 25.0%|1MiB/s|00:03|NA|25|NA|NA|22")
    )
    assert progress.total_percent == 25
    assert progress.total_bytes is None


def test_cover_only_command_has_no_media_format_args(tmp_path: Path) -> None:
    req = request(
        mode="cover",
        media_title="封面测试",
        media_id="abc",
        filename_template="{title}-{id}",
        download_subtitles=True,
    )
    args = YtDlpService().build_download_args(req, tmp_path)
    assert "--skip-download" in args
    assert "--write-thumbnail" in args
    assert "--format" not in args
    assert "--write-subs" not in args
    assert "--write-auto-subs" not in args
    assert any("封面测试-abc" in item for item in args)
