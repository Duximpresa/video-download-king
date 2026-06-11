from __future__ import annotations

from collections import deque
from pathlib import Path
import shutil

from PIL import Image, ImageChops


ROOT = Path(__file__).resolve().parents[1]
VERSION_DIR = ROOT / "branding" / "logo" / "v1"
SOURCE = VERSION_DIR / "source" / "selected-logo-original.png"
MASTER_DIR = VERSION_DIR / "master"
PNG_DIR = VERSION_DIR / "png"
WINDOWS_DIR = VERSION_DIR / "windows"
WEB_DIR = VERSION_DIR / "web"
PREVIEW_DIR = VERSION_DIR / "preview"
APP_ASSETS = ROOT / "video_download_king" / "assets"

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def is_background(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return min(pixel) >= 175 and max(pixel) - min(pixel) <= 18


def remove_connected_checkerboard(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    width, height = rgb.size
    source = rgb.load()
    visited = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def enqueue(x: int, y: int) -> None:
        index = y * width + x
        if not visited[index] and is_background(source[x, y]):
            visited[index] = 1
            queue.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        if x:
            enqueue(x - 1, y)
        if x + 1 < width:
            enqueue(x + 1, y)
        if y:
            enqueue(x, y - 1)
        if y + 1 < height:
            enqueue(x, y + 1)

    rgba = rgb.convert("RGBA")
    alpha = Image.new("L", rgb.size, 255)
    alpha_data = alpha.load()
    for y in range(height):
        row = y * width
        for x in range(width):
            if visited[row + x]:
                alpha_data[x, y] = 0
    rgba.putalpha(alpha)
    return rgba


def fit_square(image: Image.Image, size: int, padding_ratio: float = 0.055) -> Image.Image:
    alpha = image.getchannel("A")
    bounds = alpha.getbbox()
    if not bounds:
        raise RuntimeError("The selected logo has no visible pixels.")
    cropped = image.crop(bounds)
    available = round(size * (1 - padding_ratio * 2))
    scale = min(available / cropped.width, available / cropped.height)
    resized = cropped.resize(
        (round(cropped.width * scale), round(cropped.height * scale)),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        resized,
        ((size - resized.width) // 2, (size - resized.height) // 2),
    )
    return canvas


def make_monochrome(image: Image.Image, foreground: tuple[int, int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    result = Image.new("RGBA", rgba.size, (*foreground, 0))
    result.putalpha(alpha)

    # Keep the light arrow and highlights as transparent negative space.
    rgb = rgba.convert("RGB")
    light = rgb.convert("L").point(lambda value: 255 if value >= 225 else 0)
    low_chroma = ImageChops.difference(
        rgb.getchannel("R"), rgb.getchannel("B")
    ).point(lambda value: 255 if value <= 24 else 0)
    holes = ImageChops.multiply(light, low_chroma)
    holes = ImageChops.multiply(holes, alpha)
    result.putalpha(ImageChops.subtract(alpha, holes))
    return result


def save_png(image: Image.Image, destination: Path, size: int) -> None:
    resized = image.resize((size, size), Image.Resampling.LANCZOS)
    resized.save(destination, format="PNG", optimize=True)


def make_preview(image: Image.Image, destination: Path) -> None:
    tile = image.resize((640, 640), Image.Resampling.LANCZOS)
    preview = Image.new("RGB", (1400, 760), "#f4f6f8")
    preview.paste(tile, (70, 60), tile)
    dark = Image.new("RGBA", (640, 640), "#17191d")
    dark.alpha_composite(tile)
    preview.paste(dark.convert("RGB"), (690, 60))
    preview.save(destination, quality=94)


def main() -> None:
    for directory in (
        MASTER_DIR,
        PNG_DIR,
        WINDOWS_DIR,
        WEB_DIR,
        PREVIEW_DIR,
        APP_ASSETS,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    transparent = remove_connected_checkerboard(Image.open(SOURCE))
    master = fit_square(transparent, 1024)
    master.save(MASTER_DIR / "video-download-king-logo-v1.png", optimize=True)

    for size in (1024, 512, 256, 128, 64):
        save_png(master, PNG_DIR / f"video-download-king-logo-v1-{size}.png", size)

    save_png(master, WEB_DIR / "favicon-32.png", 32)
    save_png(master, WEB_DIR / "apple-touch-icon-180.png", 180)
    save_png(master, WEB_DIR / "web-app-icon-512.png", 512)

    frames = []
    for size in ICO_SIZES:
        frame = master.resize((size, size), Image.Resampling.LANCZOS)
        frames.append(frame)
    frames[-1].save(
        WINDOWS_DIR / "video-download-king-v1.ico",
        format="ICO",
        append_images=frames[:-1],
        sizes=[(size, size) for size in ICO_SIZES],
    )

    black = make_monochrome(master, (0, 0, 0))
    white = make_monochrome(master, (255, 255, 255))
    black.save(PNG_DIR / "video-download-king-logo-v1-mono-black.png", optimize=True)
    white.save(PNG_DIR / "video-download-king-logo-v1-mono-white.png", optimize=True)
    make_preview(master, PREVIEW_DIR / "logo-v1-light-dark-preview.jpg")

    shutil.copy2(PNG_DIR / "video-download-king-logo-v1-1024.png", APP_ASSETS / "logo-1024.png")
    shutil.copy2(PNG_DIR / "video-download-king-logo-v1-512.png", APP_ASSETS / "logo-512.png")
    shutil.copy2(WEB_DIR / "favicon-32.png", APP_ASSETS / "favicon-32.png")
    shutil.copy2(WEB_DIR / "apple-touch-icon-180.png", APP_ASSETS / "apple-touch-icon.png")
    shutil.copy2(WINDOWS_DIR / "video-download-king-v1.ico", APP_ASSETS / "logo.ico")

    # Standard web favicon name, stored beside the PNG favicon.
    frames[2].save(
        WEB_DIR / "favicon.ico",
        format="ICO",
        append_images=[frames[0]],
        sizes=[(16, 16), (32, 32)],
    )


if __name__ == "__main__":
    main()
