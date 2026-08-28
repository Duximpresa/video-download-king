from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp_socks import ProxyConnector

from video_download_king.models import XiaohongshuAsset, XiaohongshuDownloadRequest
from video_download_king.config import SettingsStore
from video_download_king.platforms import detect_platform
from video_download_king.xiaohongshu import (
    XiaohongshuService,
    extract_note_data,
    extract_xiaohongshu_url,
    image_url,
    load_xiaohongshu_cookies,
    parse_initial_state,
    resolve_xiaohongshu_output_dir,
    select_video_asset,
    validate_xiaohongshu_url,
)


NOTE_URL = "https://www.xiaohongshu.com/explore/65abcdef0000000012345678?xsec_token=token"


def _html(state: dict, *, undefined: bool = False) -> str:
    payload = json.dumps(state, ensure_ascii=False)
    if undefined:
        payload = payload[:-1] + ',"optional":undefined}'
    return f"<html><script>window.__INITIAL_STATE__={payload}</script></html>"


def test_xiaohongshu_url_and_share_text_validation() -> None:
    assert extract_xiaohongshu_url(f"复制这条笔记 {NOTE_URL} 打开小红书") == NOTE_URL
    assert extract_xiaohongshu_url("xhslink.com/m/abc123") == "https://xhslink.com/m/abc123"
    assert validate_xiaohongshu_url(NOTE_URL) == NOTE_URL
    assert detect_platform(NOTE_URL) == "小红书"
    with pytest.raises(ValueError):
        validate_xiaohongshu_url("https://www.xiaohongshu.com/user/profile/abcdef")
    with pytest.raises(ValueError):
        validate_xiaohongshu_url(f"{NOTE_URL} {NOTE_URL}")


def test_initial_state_desktop_mobile_and_javascript_values() -> None:
    note = {"noteId": "1", "title": "标题", "type": "normal", "imageList": []}
    desktop = parse_initial_state(_html({"note": {"noteDetailMap": {"1": {"note": note}}}}, undefined=True))
    assert extract_note_data(desktop)["title"] == "标题"
    mobile = parse_initial_state(_html({"noteData": {"data": {"noteData": note}}}))
    assert extract_note_data(mobile)["noteId"] == "1"
    mapped = parse_initial_state(
        '<script>window.__INITIAL_STATE__={"cache":new Map([]),'
        '"spaced":new Map ( [ ] ),"text":"new Map([])"}</script>'
    )
    assert mapped == {"cache": [], "spaced": [], "text": "new Map([])"}


def test_media_parses_video_images_and_live_photo() -> None:
    gallery = XiaohongshuService._media_from_note(
        NOTE_URL,
        {
            "noteId": "1", "title": "图文", "desc": "说明", "type": "normal", "time": 1700000000000,
            "user": {"nickname": "作者", "userId": "u1"},
            "imageList": [
                {"urlDefault": "https://sns-img-bd.xhscdn.com/spectrum/one!abc", "stream": {"h264": [{"masterUrl": "https://cdn/live.mp4"}]}},
                {"url": "https://sns-img-bd.xhscdn.com/spectrum/two"},
            ],
        },
        "webp",
    )
    assert gallery.media_type == "gallery"
    assert len(gallery.image_assets) == 2
    assert gallery.image_assets[0].urls[0].endswith("spectrum/one?imageView2/format/webp")
    assert gallery.live_assets[0].urls == ("https://cdn/live.mp4",)

    video = XiaohongshuService._media_from_note(
        NOTE_URL,
        {"noteId": "2", "title": "视频", "type": "video", "imageList": [{}], "video": {"consumer": {"originVideoKey": "origin/key"}}},
    )
    assert video.media_type == "video"
    assert video.video_assets[0].codec == "original"

    current_video = XiaohongshuService._media_from_note(
        NOTE_URL,
        {
            "noteId": "3", "title": "新视频流", "type": "video", "imageList": [{}],
            "video": {"media": {"stream": {"EF4": [{
                "masterUrl": "https://cdn/current.mp4", "videoCodec": "h264",
                "width": 1920, "height": 1080, "videoBitrate": 2000, "size": 100,
            }]}}},
        },
    )
    assert current_video.video_assets[0].urls == ("https://cdn/current.mp4",)
    assert current_video.video_assets[0].codec == "h264"


def test_video_selection_and_image_url() -> None:
    assets = [
        XiaohongshuAsset("video", ("low",), width=720, height=480, bitrate=900, size=50),
        XiaohongshuAsset("video", ("high",), width=1920, height=1080, bitrate=2000, size=100),
    ]
    assert select_video_asset(assets, "resolution").urls == ("high",)
    assert select_video_asset(assets, "bitrate").urls == ("high",)
    assert select_video_asset(assets, "size").urls == ("low",)
    assert image_url("https://sns-img-bd.xhscdn.com/a/b!tag", "auto").endswith("/a/b")
    assert image_url("https://sns-webpic.xhscdn.com/20260714/signature/stable-token!tag", "auto").endswith("/stable-token")


def test_cookie_filter_proxy_and_output_path(tmp_path: Path) -> None:
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n.xiaohongshu.com\tTRUE\t/\tFALSE\t2147483647\tweb_session\tabc\n.example.com\tTRUE\t/\tFALSE\t2147483647\tignored\tvalue\n", encoding="utf-8")
    assert load_xiaohongshu_cookies(str(cookie)) == {"web_session": "abc"}
    cookie.write_text("# Netscape HTTP Cookie File\n#HttpOnly_.xiaohongshu.com\tTRUE\t/\tTRUE\t2147483647\ta1\t值\nmalformed\n", encoding="utf-8-sig")
    assert load_xiaohongshu_cookies(str(cookie)) == {"a1": "值"}

    async def check_proxy() -> None:
        connector, proxy = XiaohongshuService._proxy_options("socks5://127.0.0.1:1080/")
        assert isinstance(connector, ProxyConnector) and proxy is None
        await connector.close()
    asyncio.run(check_proxy())

    request = XiaohongshuDownloadRequest(NOTE_URL, tmp_path, classify_by_author=True)
    assert resolve_xiaohongshu_output_dir(request, "作者:测试").relative_to(tmp_path).parts == ("小红书", "作者_测试")


def test_xiaohongshu_settings_defaults_and_persistence(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    settings = store.load()
    assert settings.xiaohongshu_video_preference == "resolution"
    assert settings.xiaohongshu_image_format == "auto"
    settings.xiaohongshu_cookie_file = "xhs-cookies.txt"
    settings.xiaohongshu_classify_by_author = True
    settings.xiaohongshu_video_preference = "bitrate"
    settings.xiaohongshu_image_format = "png"
    store.save(settings)
    loaded = store.load()
    assert loaded.xiaohongshu_cookie_file == "xhs-cookies.txt"
    assert loaded.xiaohongshu_classify_by_author
    assert loaded.xiaohongshu_video_preference == "bitrate"
    assert loaded.xiaohongshu_image_format == "png"
