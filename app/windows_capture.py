from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageGrab


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class ContentRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def list_windows() -> list[WindowInfo]:
    windows: list[WindowInfo] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        windows.append(
            WindowInfo(
                hwnd=hwnd,
                title=buffer.value,
                left=rect.left,
                top=rect.top,
                right=rect.right,
                bottom=rect.bottom,
            )
        )
        return True

    user32.EnumWindows(callback, 0)
    return windows


def find_memu_window() -> WindowInfo:
    candidates = []
    for window in list_windows():
        title = window.title.lower()
        if "kingdom guard" in title or "memu" in title:
            candidates.append(window)
    if not candidates:
        raise RuntimeError("Не удалось найти окно MEmu/Kingdom Guard")
    candidates.sort(key=lambda item: item.width * item.height, reverse=True)
    return candidates[0]


def grab_rect(rect: ContentRect) -> Image.Image:
    return ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom)).convert("RGB")


def capture_window_printwindow(window: WindowInfo) -> Image.Image:
    width = window.width
    height = window.height

    hwnd_dc = user32.GetWindowDC(window.hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)

    PW_RENDERFULLCONTENT = 0x00000002
    result = user32.PrintWindow(window.hwnd, mem_dc, PW_RENDERFULLCONTENT)
    if result != 1:
        user32.PrintWindow(window.hwnd, mem_dc, 0)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [
            ("bmiHeader", BITMAPINFOHEADER),
            ("bmiColors", wintypes.DWORD * 3),
        ]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0

    buffer_len = width * height * 4
    buffer = ctypes.create_string_buffer(buffer_len)
    bits = gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(bmi), 0)
    if bits != height:
        raise RuntimeError("Не удалось получить bitmap через PrintWindow")

    image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(window.hwnd, hwnd_dc)
    return image


def _resize_array(image: Image.Image, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(image.convert("L").resize(size, Image.Resampling.BILINEAR), dtype=np.float32)


def _score_region(window_image: Image.Image, adb_image: Image.Image, left: int, top: int, size: int) -> float:
    crop = window_image.crop((left, top, left + size, top + size))
    lhs = _resize_array(crop, (64, 64))
    rhs = _resize_array(adb_image, (64, 64))
    return float(np.mean(np.abs(lhs - rhs)))


def infer_android_content_rect(window: WindowInfo, adb_image: Image.Image) -> ContentRect:
    window_image = capture_window_printwindow(window)
    best: tuple[float, ContentRect] | None = None

    left_options = range(0, 7, 2)
    top_options = range(26, 39, 2)
    right_options = range(36, 55, 2)
    bottom_options = range(0, 5, 2)

    for left_margin in left_options:
        for top_margin in top_options:
            for right_margin in right_options:
                for bottom_margin in bottom_options:
                    size = min(
                        window.width - left_margin - right_margin,
                        window.height - top_margin - bottom_margin,
                    )
                    if size < 400:
                        continue
                    left = left_margin
                    top = top_margin
                    score = _score_region(window_image, adb_image, left, top, size)
                    rect = ContentRect(
                        left=window.left + left,
                        top=window.top + top,
                        right=window.left + left + size,
                        bottom=window.top + top + size,
                    )
                    if best is None or score < best[0]:
                        best = (score, rect)

    if best is None:
        raise RuntimeError("Не удалось вычислить область Android-контента в окне MEmu")

    _, coarse = best
    coarse_window = ContentRect(
        left=coarse.left - window.left,
        top=coarse.top - window.top,
        right=coarse.right - window.left,
        bottom=coarse.bottom - window.top,
    )
    best = None
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            for ds in range(-2, 3):
                left = coarse_window.left + dx
                top = coarse_window.top + dy
                size = coarse_window.width + ds
                if left < 0 or top < 0 or size < 400:
                    continue
                if left + size > window.width or top + size > window.height:
                    continue
                score = _score_region(window_image, adb_image, left, top, size)
                rect = ContentRect(
                    left=window.left + left,
                    top=window.top + top,
                    right=window.left + left + size,
                    bottom=window.top + top + size,
                )
                if best is None or score < best[0]:
                    best = (score, rect)

    if best is None:
        raise RuntimeError("Не удалось уточнить область Android-контента")
    return best[1]


def capture_android_content(window: WindowInfo, content_rect: ContentRect, adb_size: tuple[int, int]) -> Image.Image:
    image = ImageGrab.grab(bbox=(content_rect.left, content_rect.top, content_rect.right, content_rect.bottom)).convert("RGB")
    return image.resize(adb_size, Image.Resampling.BILINEAR)


def capture_android_content_printwindow(window: WindowInfo, content_rect: ContentRect, adb_size: tuple[int, int]) -> Image.Image:
    window_image = capture_window_printwindow(window)
    local_left = content_rect.left - window.left
    local_top = content_rect.top - window.top
    local_right = content_rect.right - window.left
    local_bottom = content_rect.bottom - window.top
    image = window_image.crop((local_left, local_top, local_right, local_bottom))
    return image.resize(adb_size, Image.Resampling.BILINEAR)
