from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def runtime_path(*parts: str) -> Path:
    return app_root().joinpath("runtime", *parts)


def yt_dlp_path() -> Path:
    return runtime_path("yt-dlp", "yt-dlp.exe")


def ffmpeg_dir() -> Path:
    return runtime_path("ffmpeg", "bin")


def ffmpeg_path() -> Path:
    return ffmpeg_dir() / "ffmpeg.exe"


def ffprobe_path() -> Path:
    return ffmpeg_dir() / "ffprobe.exe"


def deno_path() -> Path:
    return runtime_path("deno", "deno.exe")


def settings_path() -> Path:
    return app_root() / "config" / "settings.json"
