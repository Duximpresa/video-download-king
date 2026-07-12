from __future__ import annotations

import re
from datetime import datetime
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
    existing_stems = {path.stem for path in directory.iterdir()} if directory.is_dir() else set()
    if stem not in existing_stems:
        return stem
    index = 1
    while f"{stem} ({index})" in existing_stems:
        index += 1
    return f"{stem} ({index})"


TEMPLATE_FIELDS = {
    "title",
    "id",
    "channel",
    "author",
    "platform",
    "upload_date",
    "download_date",
    "type",
    "index",
    "asset",
    "bvid",
    "aid",
    "uploader",
    "page",
    "part_title",
}
TEMPLATE_TOKEN = re.compile(r"\{([a-z_]+)\}")


def display_date(value: str) -> str:
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def render_filename_template(template: str, values: dict[str, str]) -> str:
    unknown = set(TEMPLATE_TOKEN.findall(template)) - TEMPLATE_FIELDS
    if unknown:
        raise ValueError(f"未知命名字段：{', '.join(sorted(unknown))}")
    data = {key: values.get(key, "") for key in TEMPLATE_FIELDS}
    data["author"] = data["author"] or data["channel"]
    data["channel"] = data["channel"] or data["author"]
    data["uploader"] = data["uploader"] or data["author"] or data["channel"]
    data["upload_date"] = display_date(data["upload_date"])
    data["download_date"] = data["download_date"] or datetime.now().strftime("%Y-%m-%d")
    rendered = TEMPLATE_TOKEN.sub(lambda match: data.get(match.group(1), ""), template)
    return sanitize_filename(rendered, 180)


def sanitize_suffix(value: str, max_length: int = 40) -> str:
    cleaned = sanitize_filename(value, max_length).strip(" .")
    if not cleaned:
        return ""
    return cleaned if cleaned.startswith(("_", "-", " ")) else f"_{cleaned}"


def has_matching_language(available: set[str], expression: str) -> bool:
    patterns = [item.strip() for item in expression.split(",") if item.strip()]
    for pattern in patterns:
        try:
            if any(re.fullmatch(pattern, language) for language in available):
                return True
        except re.error:
            if pattern in available:
                return True
    return False


def human_size(size: int | None) -> str:
    if not size:
        return "未知"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return "未知"
