from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from video_download_king.douyin import DouyinService, load_netscape_cookies, render_gallery_folder_name, resolve_douyin_output_dir, select_video_asset
from video_download_king.douyin_workers import _yt_request
from video_download_king.models import (
    DouyinAsset,
    DouyinDownloadRequest,
    DouyinMediaInfo,
)
from aiohttp_socks import ProxyConnector
from video_download_king.platforms import (
    detect_platform,
    extract_douyin_url,
    validate_douyin_url,
)


VIDEO_URL = "https://www.douyin.com/video/7604129988555574538"


def test_douyin_platform_and_share_text_extraction() -> None:
    share = f"复制打开抖音，看看这个作品 {VIDEO_URL} 03/28"
    assert extract_douyin_url(share) == VIDEO_URL
    assert detect_platform(share) == "Douyin"
    assert validate_douyin_url(share) == VIDEO_URL
    assert validate_douyin_url("v.douyin.com/abc/") == "https://v.douyin.com/abc/"
    with pytest.raises(ValueError):
        validate_douyin_url("https://www.douyin.com/user/example")
    with pytest.raises(ValueError):
        validate_douyin_url("https://live.douyin.com/123")


def test_netscape_cookie_file(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".douyin.com\tTRUE\t/\tFALSE\t2147483647\tttwid\tabc\n"
        ".example.com\tTRUE\t/\tFALSE\t2147483647\tignored\tvalue\n",
        encoding="utf-8",
    )
    assert load_netscape_cookies(str(cookie_file)) == {"ttwid": "abc"}
    with pytest.raises(ValueError):
        load_netscape_cookies(str(tmp_path / "missing.txt"))


def test_native_socks_proxy_uses_connector() -> None:
    async def create_connector() -> None:
        connector, request_proxy = DouyinService._proxy_options("socks5://127.0.0.1:1080/")
        assert isinstance(connector, ProxyConnector)
        assert request_proxy is None
        await connector.close()

    asyncio.run(create_connector())
    connector, request_proxy = DouyinService._proxy_options("http://127.0.0.1:7890/")
    assert connector is None
    assert request_proxy == "http://127.0.0.1:7890/"


def test_quality_selection() -> None:
    assets = [
        DouyinAsset("video", ("unknown",), width=720, height=495, watermarked=True),
        DouyinAsset("video", ("silent",), width=1920, height=1080, bitrate=3_000_000, codec="1080_1_1"),
        DouyinAsset("video", ("low",), width=960, height=540, bitrate=500_000, codec="low_540_0"),
        DouyinAsset("video", ("mid",), width=1280, height=720, bitrate=1_000_000, codec="normal_720_0"),
        DouyinAsset("video", ("high",), width=1920, height=1080, bitrate=2_000_000, codec="normal_1080_0"),
    ]
    assert select_video_asset(assets, "highest").urls == ("high",)
    assert select_video_asset(assets, "lowest").urls == ("low",)
    assert select_video_asset(assets, "720p").urls == ("mid",)
    assert select_video_asset(assets, "asset:1").urls == ("silent",)
    with pytest.raises(ValueError, match="重新分析"):
        select_video_asset(assets, "asset:99")


def test_detail_parses_video_and_prefers_clean_urls() -> None:
    media = DouyinService._media_from_detail(
        VIDEO_URL,
        {
            "aweme_id": "7604129988555574538",
            "desc": "测试视频",
            "author": {"nickname": "作者"},
            "video": {
                "duration": 12_000,
                "origin_cover": {"url_list": ["https://cdn.example/cover.jpg"]},
                "bit_rate": [
                    {
                        "bit_rate": 2_000_000,
                        "play_addr": {
                            "width": 1920,
                            "height": 1080,
                            "uri": "video-id",
                            "url_list": [
                                "https://cdn.example/playwm.mp4?watermark=1",
                                "https://cdn.example/clean.mp4",
                            ],
                        },
                    }
                ],
            },
        },
    )
    assert media.media_type == "video"
    assert media.duration == 12
    assert media.video_assets[0].urls[0] == "https://cdn.example/clean.mp4"


def test_detail_parses_gallery_originals_and_live_photos() -> None:
    media = DouyinService._media_from_detail(
        "https://www.douyin.com/note/7104586575937326343",
        {
            "aweme_id": "7104586575937326343",
            "desc": "测试图集",
            "image_post_info": {
                "images": [
                    {
                        "origin_image": {"url_list": ["https://cdn.example/01.jpg"]},
                        "owner_watermark_image": {
                            "url_list": ["https://cdn.example/owner_watermark_01.jpg"]
                        },
                        "video": {
                            "play_addr_h264": {
                                "url_list": ["https://cdn.example/01-live.mp4"]
                            }
                        },
                    },
                    {"display_image": {"url_list": ["https://cdn.example/02.webp"]}},
                ]
            },
        },
    )
    assert media.media_type == "gallery"
    assert [(item.kind, item.index) for item in media.gallery_assets] == [
        ("image", 1),
        ("live_photo", 1),
        ("image", 2),
    ]
    assert media.gallery_assets[0].urls[0].endswith("01.jpg")


def test_ytdlp_request_maps_douyin_quality() -> None:
    request = DouyinDownloadRequest(
        url=VIDEO_URL,
        output_dir=Path("downloads"),
        quality="540p",
    )
    media = DouyinMediaInfo(VIDEO_URL, "1", "标题", author="作者")
    mapped = _yt_request(request, media)
    assert mapped.media_platform == "Douyin"
    assert mapped.quality_preset == "custom"
    assert mapped.custom_height == 540
    assert mapped.cookie_file == ""


def test_douyin_author_output_directory_is_sanitized(tmp_path: Path) -> None:
    request = DouyinDownloadRequest(
        url=VIDEO_URL,
        output_dir=tmp_path,
        classify_by_platform=True,
        classify_by_author=True,
    )
    assert resolve_douyin_output_dir(request, "作者:测试").relative_to(tmp_path).parts == (
        "Douyin",
        "作者_测试",
    )
    assert resolve_douyin_output_dir(request, "").relative_to(tmp_path).parts == (
        "Douyin",
        "未知作者",
    )


def test_gallery_folder_name_blanks_asset_fields_and_falls_back() -> None:
    media = DouyinMediaInfo(VIDEO_URL, "123", "作品标题", media_type="gallery")
    assert render_gallery_folder_name("{title}_{index}-{asset}", media) == "作品标题"
    assert render_gallery_folder_name("{index}{asset}", media) == "作品标题 [123]"


@pytest.mark.parametrize(
    ("assets", "download_cover", "failed_urls", "expects_folder"),
    [
        ([DouyinAsset("image", ("one",), index=1, extension=".jpg")], False, set(), False),
        ([DouyinAsset("image", ("one",), index=1, extension=".jpg"), DouyinAsset("image", ("two",), index=2, extension=".jpg")], False, set(), True),
        ([DouyinAsset("image", ("one",), index=1, extension=".jpg"), DouyinAsset("live_photo", ("live",), index=1, extension=".mp4")], False, set(), True),
        ([DouyinAsset("image", ("one",), index=1, extension=".jpg")], True, set(), True),
        ([DouyinAsset("image", ("one",), index=1, extension=".jpg"), DouyinAsset("image", ("fail",), index=2, extension=".jpg")], False, {"fail"}, False),
    ],
)
def test_gallery_uses_actual_saved_file_count_for_folder(
    tmp_path: Path,
    monkeypatch,
    assets: list[DouyinAsset],
    download_cover: bool,
    failed_urls: set[str],
    expects_folder: bool,
) -> None:
    media = DouyinMediaInfo(
        VIDEO_URL,
        "123",
        "作品标题",
        media_type="gallery",
        gallery_assets=assets,
        cover_asset=DouyinAsset("cover", ("cover",), extension=".jpg"),
    )
    request = DouyinDownloadRequest(
        VIDEO_URL,
        tmp_path,
        filename_template="{title}_{index}_{asset}",
        classify_by_platform=False,
        download_thumbnail=download_cover,
        media=media,
    )
    service = DouyinService()

    async def fake_download(session, asset, path, proxy, item_index, total_items, on_progress, on_log):
        if asset.urls[0] in failed_urls:
            raise RuntimeError("模拟失败")
        path.write_bytes(asset.urls[0].encode())
        return path

    monkeypatch.setattr(service, "_download_asset", fake_download)
    outputs = service.download(request, lambda progress: None, lambda message: None)
    assert len(outputs) == (len(assets) - len(failed_urls) + int(download_cover))
    assert all(path.exists() for path in outputs)
    if expects_folder:
        assert {path.parent for path in outputs} == {tmp_path / "作品标题"}
    else:
        assert all(path.parent == tmp_path for path in outputs)


def test_gallery_duplicate_folder_gets_sequence(tmp_path: Path, monkeypatch) -> None:
    media = DouyinMediaInfo(
        VIDEO_URL,
        "123",
        "作品标题",
        media_type="gallery",
        gallery_assets=[
            DouyinAsset("image", ("one",), index=1, extension=".jpg"),
            DouyinAsset("image", ("two",), index=2, extension=".jpg"),
        ],
    )
    request = DouyinDownloadRequest(VIDEO_URL, tmp_path, classify_by_platform=False, media=media)
    service = DouyinService()

    async def fake_download(session, asset, path, proxy, item_index, total_items, on_progress, on_log):
        path.write_bytes(b"ok")
        return path

    monkeypatch.setattr(service, "_download_asset", fake_download)
    first = service.download(request, lambda progress: None, lambda message: None)
    second = service.download(request, lambda progress: None, lambda message: None)
    assert first[0].parent == tmp_path / "作品标题 [123]"
    assert second[0].parent == tmp_path / "作品标题 [123] (1)"
