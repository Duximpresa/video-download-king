from __future__ import annotations

import io
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressBar

from video_download_king.bilibili import (
    BilibiliService,
    extract_bilibili_url,
    parse_bilibili_identifier,
    select_audio_stream,
    select_video_stream,
    sign_wbi,
    load_netscape_cookies,
)
from video_download_king.bilibili_page import BilibiliPage
from video_download_king.config import AppSettings, SettingsStore
from video_download_king.models import (
    BilibiliMediaInfo,
    BilibiliPartInfo,
    BilibiliStreamInfo,
)
from video_download_king.utils import unique_media_stem


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_bilibili_share_text_and_identifier_parsing() -> None:
    url = extract_bilibili_url("复制链接 https://www.bilibili.com/video/BV1Ab411c7mD?p=3 看视频")
    assert url == "https://www.bilibili.com/video/BV1Ab411c7mD?p=3"
    assert parse_bilibili_identifier(url) == ("bvid", "BV1Ab411c7mD", 3)
    assert parse_bilibili_identifier("https://www.bilibili.com/video/av12345") == ("aid", 12345, None)


def test_wbi_signature_is_stable() -> None:
    signed = sign_wbi(
        {"bvid": "BV1xx411c7mD", "cid": 123, "fnval": 4048},
        "7cd084941338484aae1ad9425b84077c",
        "4932caff0ff746eab6f01bf08b70ac45",
        1700000000,
    )
    assert signed["wts"] == "1700000000"
    assert signed["w_rid"] == "f8bbd47098b2e1809ce49009aa3cf216"


def test_stream_selection_fallback_rules() -> None:
    streams = [
        BilibiliStreamInfo("video", 80, "1080P", "hevc"),
        BilibiliStreamInfo("video", 80, "1080P", "avc"),
        BilibiliStreamInfo("video", 64, "720P", "avc"),
    ]
    assert select_video_stream(streams, 80, "av1").codec == "avc"
    assert select_video_stream(streams, 64, "hevc").stream_id == 64
    audio = [BilibiliStreamInfo("audio", 30216, "64K"), BilibiliStreamInfo("audio", 30280, "192K")]
    assert select_audio_stream(audio, 30232).stream_id == 30216


def test_utf8_cookie_export_loads_only_bilibili_rows(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t0\tnote\t中文\n"
        ".bilibili.com\tTRUE\t/\tTRUE\t2147483647\tSESSDATA\tabc%2Cdef\n",
        encoding="utf-8",
    )
    jar = load_netscape_cookies(str(cookie_file))
    assert [(cookie.domain, cookie.name) for cookie in jar] == [(".bilibili.com", "SESSDATA")]


class _Response(io.BytesIO):
    def __init__(self, data: bytes, status: int = 206) -> None:
        super().__init__(data); self.status = status; self.headers = {"Content-Length": str(len(data))}
    def __enter__(self): return self
    def __exit__(self, *_args): self.close()


def test_range_download_and_non_range_fallback(tmp_path: Path) -> None:
    payload = b"0123456789" * 100
    service = BilibiliService()
    service._remote_size = lambda _urls, _referer: ("https://cdn.test/file", len(payload))  # type: ignore[method-assign]
    def ranged(_url, *, headers=None, method=None):
        assert method is None
        start, end = [int(item) for item in headers["Range"].removeprefix("bytes=").split("-")]
        return _Response(payload[start:end + 1])
    service._open = ranged  # type: ignore[method-assign]
    target = tmp_path / "range.m4s"
    service._download_stream(BilibiliStreamInfo("video", 80, "1080P", urls=("https://cdn.test/file",)), target, "https://ref", lambda *_: None)
    assert target.read_bytes() == payload

    def no_range(_url, *, headers=None, method=None):
        return _Response(payload, status=200)
    service._open = no_range  # type: ignore[method-assign]
    target = tmp_path / "sequential.m4s"
    service._download_stream(BilibiliStreamInfo("video", 80, "1080P", urls=("https://cdn.test/file",)), target, "https://ref", lambda *_: None)
    assert target.read_bytes() == payload


def test_unique_media_stem_treats_brackets_as_plain_text(tmp_path: Path) -> None:
    (tmp_path / "标题 [BV123].mp4").write_bytes(b"x")
    assert unique_media_stem(tmp_path, "标题 [BV123]") == "标题 [BV123] (1)"

def test_bilibili_page_part_defaults_and_no_transcode(tmp_path: Path) -> None:
    app()
    settings = AppSettings(save_path=str(tmp_path), bilibili_cookie_file="bili.txt")
    page = BilibiliPage(settings, SettingsStore(tmp_path / "settings.json"))
    page.url_edit.setText("https://www.bilibili.com/video/BV1Ab411c7mD?p=2")
    part1 = BilibiliPartInfo(1, 1, "第一集", selected=False)
    part2 = BilibiliPartInfo(
        2, 2, "第二集", selected=True,
        video_streams=[
            BilibiliStreamInfo(
                "video", 80, "1080P", "avc", 1920, 1080, "60", 4_000_000
            ),
            BilibiliStreamInfo(
                "video", 80, "1080P", "hevc", 1920, 1080, "60", 3_000_000
            ),
        ],
        audio_streams=[BilibiliStreamInfo("audio", 30280, "192K")],
    )
    page._analysis_complete(BilibiliMediaInfo("https://www.bilibili.com/video/BV1Ab411c7mD", "BV1Ab411c7mD", 123, "测试", "UP", parts=[part1, part2]))
    assert page.parts_table.item(0, 0).checkState() == Qt.Unchecked
    assert page.parts_table.item(1, 0).checkState() == Qt.Checked
    request = page._request()
    assert request.selected_pages == [2]
    assert page.video_version.count() == 2
    assert "1920×1080" in page.video_version.currentText()
    assert "AVC / H.264" in page.video_version.currentText()
    assert request.video_quality == 80
    assert request.video_codec == "avc"
    page.video_version.setCurrentIndex(page.video_version.findData("80:hevc"))
    assert page._request().video_codec == "hevc"
    assert request.cookie_file == "bili.txt"
    assert not hasattr(page, "transcode_panel")
    assert len(page.findChildren(QProgressBar)) == 2
    assert page.open_folder_button.text() == "打开保存目录"
    page.close()


def test_bilibili_page_uses_legacy_site_cookie_as_compatibility_fallback(tmp_path: Path) -> None:
    app()
    settings = AppSettings(save_path=str(tmp_path), cookie_file="legacy.txt", bilibili_cookie_file="")
    page = BilibiliPage(settings, SettingsStore(tmp_path / "settings.json"))
    page.url_edit.setText("https://www.bilibili.com/video/BV1Ab411c7mD")
    assert page._request().cookie_file == "legacy.txt"
    page.close()
