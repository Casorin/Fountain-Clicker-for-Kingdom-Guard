from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from app.adb_client import AdbClient
from app.config import Rect


def _decode_raw_screencap(raw_bytes: bytes) -> Image.Image:
    width = int.from_bytes(raw_bytes[0:4], "little", signed=False)
    height = int.from_bytes(raw_bytes[4:8], "little", signed=False)
    pixel_format = int.from_bytes(raw_bytes[8:12], "little", signed=False)
    if pixel_format != 1:
        raise ValueError(f"Unsupported raw screencap pixel format: {pixel_format}")
    expected = 12 + width * height * 4
    if width <= 0 or height <= 0 or len(raw_bytes) < expected:
        raise ValueError("Raw screencap payload is incomplete")
    payload = raw_bytes[12:expected]
    return Image.frombytes("RGBA", (width, height), payload).convert("RGB")


def save_screen(adb: AdbClient, screen_path: Path, backend: str = "png", save: bool = True) -> Image.Image:
    if backend == "raw":
        image = _decode_raw_screencap(adb.capture_screen_raw())
    else:
        png_bytes = adb.capture_screen()
        image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    if save:
        screen_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(screen_path)
    return image


def crop_rect(image: Image.Image, rect: Rect, output_path: Path | None = None) -> Image.Image:
    crop = image.crop((rect.left, rect.top, rect.right, rect.bottom))
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(output_path)
    return crop
