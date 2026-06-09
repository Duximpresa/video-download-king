from __future__ import annotations

import re
from pathlib import Path


INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(value: str, max_length: int = 180) -> str:
    value = INVALID_FILENAME.sub("_", value).strip().rstrip(". ")
    value = re.sub(r"\s+", " ", value)
    return (value or "未命名视频")[:max_length].rstrip(". ")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def unique_media_stem(directory: Path, stem: str) -> str:
    if not any(directory.glob(f"{stem}.*")):
        return stem
    index = 1
    while any(directory.glob(f"{stem} ({index}).*")):
        index += 1
    return f"{stem} ({index})"


def human_size(size: int | None) -> str:
    if not size:
        return "未知"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return "未知"
