from __future__ import annotations

import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
import statistics

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from app.fast_ocr import FastOcrResult, recognize_digits_from_templates
from app.config import AppConfig


@dataclass(frozen=True)
class RecognitionResult:
    raw_text: str
    normalized_text: str
    value: int | None
    variant_name: str
    confidence: float
    method: str
    fallback_used: bool
    fast_reason: str = ""


@dataclass(frozen=True)
class TextRecognitionResult:
    raw_text: str
    normalized_text: str
    variant_name: str


@dataclass(frozen=True)
class OcrCandidate:
    raw_text: str
    normalized_text: str
    value: int
    variant_name: str
    confidence: float


class WindowsOcrTimeoutError(RuntimeError):
    pass


def _threshold(image: Image.Image, cutoff: int, invert: bool = False) -> Image.Image:
    if invert:
        return image.point(lambda px: 255 if px < cutoff else 0, mode="1").convert("L")
    return image.point(lambda px: 255 if px >= cutoff else 0, mode="1").convert("L")


def extract_digit_roi(image: Image.Image) -> Image.Image:
    left = int(image.width * 0.18)
    top = int(image.height * 0.00)
    right = int(image.width * 0.80)
    bottom = int(image.height * 0.68)
    return image.crop((left, top, right, bottom)).convert("RGB")


def temporal_median_image(images: list[Image.Image], frame_count: int) -> Image.Image | None:
    if frame_count <= 0 or len(images) < frame_count:
        return None
    recent = images[-frame_count:]
    size = recent[-1].size
    if any(image.size != size for image in recent):
        return None
    stack = np.stack([np.asarray(image.convert("RGB"), dtype=np.uint8) for image in recent], axis=0)
    median = np.median(stack, axis=0).astype(np.uint8)
    return Image.fromarray(median, mode="RGB")


def _digit_color_mask(image: Image.Image) -> Image.Image:
    rgb = np.array(image.convert("RGB"), dtype=np.uint8)
    brightness = rgb.mean(axis=2)
    warm_digits = (rgb[:, :, 0] >= 150) & (rgb[:, :, 1] >= 125) & (rgb[:, :, 2] <= 180)
    bright_white = (brightness >= 185) & ((rgb.max(axis=2) - rgb.min(axis=2)) <= 95)
    mask = warm_digits | bright_white
    return Image.fromarray((mask.astype(np.uint8) * 255), mode="L")


def _render_variants(image: Image.Image) -> list[tuple[str, Image.Image]]:
    digit_roi = extract_digit_roi(image)
    enlarged_rgb = digit_roi.resize((digit_roi.width * 4, digit_roi.height * 4), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(enlarged_rgb)
    sharpened = gray.filter(ImageFilter.SHARPEN)
    contrast = ImageOps.autocontrast(sharpened)
    blurred = contrast.filter(ImageFilter.MedianFilter(size=3))
    color_mask = _digit_color_mask(enlarged_rgb).filter(ImageFilter.MedianFilter(size=3))
    return [
        ("roi_rgb_x4", enlarged_rgb),
        ("gray_x4", gray),
        ("contrast_x4", contrast),
        ("threshold_165_x4", _threshold(contrast, 165)),
        ("threshold_185_x4", _threshold(contrast, 185)),
        ("color_mask_x4", color_mask),
        ("invert_140_x4", _threshold(blurred, 140, invert=True)),
    ]


def _extract_int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    if len(digits) < 4:
        return None
    try:
        value = int(digits)
    except ValueError:
        return None
    if value <= 0 or value > 9_999_999:
        return None
    return value


def _run_windows_ocr(image_path: Path, timeout_seconds: float | None = None) -> str:
    script_path = Path(__file__).resolve().parents[1] / "tools" / "windows_ocr_test.ps1"
    temp_dir = Path(tempfile.gettempdir())
    ascii_copy = temp_dir / image_path.name
    Image.open(image_path).save(ascii_copy)

    try:
        completed = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-ImagePath",
                str(ascii_copy),
            ],
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise WindowsOcrTimeoutError(
            f"Windows OCR timeout after {timeout_seconds:.2f}s for {image_path.name}"
        ) from exc
    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        raise RuntimeError(stderr or stdout or "Windows OCR failed")
    return stdout


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _temp_variant_path(prefix: str, variant_name: str) -> Path:
    temp_dir = Path(tempfile.gettempdir())
    return temp_dir / f"{prefix}_{variant_name}_{time.time_ns()}.png"


def save_prize_ocr_debug_variants(image: Image.Image, debug_dir: Path) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    extract_digit_roi(image).save(debug_dir / "digit_roi.png")
    for variant_name, variant in _render_variants(image):
        variant.save(debug_dir / f"prize_{variant_name}.png")


def _choose_best_candidate(candidates: list[OcrCandidate]) -> RecognitionResult:
    grouped: dict[int, list[OcrCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.value, []).append(candidate)

    def sort_key(item: tuple[int, list[OcrCandidate]]) -> tuple[int, float, int]:
        value, rows = item
        return (len(rows), statistics.mean(candidate.confidence for candidate in rows), -value)

    best_value, best_rows = max(grouped.items(), key=sort_key)
    chosen = max(best_rows, key=lambda candidate: candidate.confidence)
    summary_parts = [
        f"{value}x{len(rows)}[{','.join(row.variant_name for row in rows)}]"
        for value, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    method = "windows_ocr_consensus" if len(best_rows) >= 2 else "windows_ocr_fallback"
    return RecognitionResult(
        raw_text=chosen.raw_text,
        normalized_text=chosen.normalized_text,
        value=best_value,
        variant_name=chosen.variant_name,
        confidence=min(0.99, 0.88 + min(0.10, 0.03 * len(best_rows))),
        method=method,
        fallback_used=True,
        fast_reason="candidates=" + "; ".join(summary_parts),
    )


def _has_early_consensus(candidates: list[OcrCandidate], required_hits: int = 2) -> bool:
    grouped: dict[int, int] = {}
    for candidate in candidates:
        grouped[candidate.value] = grouped.get(candidate.value, 0) + 1
        if grouped[candidate.value] >= required_hits:
            return True
    return False


def recognize_prize_value_windows_only(image: Image.Image, debug_dir: Path | None = None) -> RecognitionResult:
    config = AppConfig()
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        extract_digit_roi(image).save(debug_dir / "digit_roi.png")
    best = RecognitionResult(
        raw_text="",
        normalized_text="",
        value=None,
        variant_name="none",
        confidence=0.0,
        method="windows_ocr_failed",
        fallback_used=True,
    )
    deadline = time.perf_counter() + max(0.1, config.windows_ocr_timeout_seconds)
    candidates: list[OcrCandidate] = []

    for variant_name, variant in _render_variants(image):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            if candidates:
                return _choose_best_candidate(candidates)
            return RecognitionResult(
                raw_text="",
                normalized_text="",
                value=None,
                variant_name=variant_name,
                confidence=0.0,
                method="windows_ocr_timeout",
                fallback_used=True,
                fast_reason=f"overall timeout {config.windows_ocr_timeout_seconds:.2f}s",
            )
        if debug_dir is not None:
            variant_path = debug_dir / f"prize_{variant_name}.png"
            variant.save(variant_path)
        else:
            variant_path = _temp_variant_path("kg_prize", variant_name)
            variant.save(variant_path)
        try:
            raw_text = _run_windows_ocr(variant_path, timeout_seconds=remaining)
        except WindowsOcrTimeoutError:
            if candidates:
                return _choose_best_candidate(candidates)
            return RecognitionResult(
                raw_text="",
                normalized_text="",
                value=None,
                variant_name=variant_name,
                confidence=0.0,
                method="windows_ocr_timeout",
                fallback_used=True,
                fast_reason=f"overall timeout {config.windows_ocr_timeout_seconds:.2f}s",
            )
        value = _extract_int(raw_text)
        current = RecognitionResult(
            raw_text=raw_text,
            normalized_text=_normalize_text(raw_text),
            value=value,
            variant_name=variant_name,
            confidence=0.91 if value is not None else 0.0,
            method="windows_ocr_fallback",
            fallback_used=True,
        )
        if current.value is not None:
            candidates.append(
                OcrCandidate(
                    raw_text=current.raw_text,
                    normalized_text=current.normalized_text,
                    value=current.value,
                    variant_name=current.variant_name,
                    confidence=current.confidence,
                )
            )
            if _has_early_consensus(candidates, required_hits=2):
                return _choose_best_candidate(candidates)
        best = current

    if candidates:
        return _choose_best_candidate(candidates)
    return best


def recognize_prize_value(
    image: Image.Image,
    debug_dir: Path | None = None,
    prefer_fast: bool | None = None,
) -> RecognitionResult:
    from app.config import AppConfig

    config = AppConfig()
    fast_enabled = config.fast_ocr_enabled if prefer_fast is None else prefer_fast
    if fast_enabled:
        fast_result: FastOcrResult = recognize_digits_from_templates(
            image,
            config.digit_template_manifest_path,
            config.fast_ocr_confidence_threshold,
        )
    else:
        fast_result = FastOcrResult(
            value=None,
            confidence=0.0,
            method="template_disabled",
            digits="",
            reason="fast OCR disabled in default monitoring mode",
            segmentation_count=0,
        )

    if fast_enabled and fast_result.value is not None and fast_result.method == "template":
        return RecognitionResult(
            raw_text=fast_result.digits,
            normalized_text=fast_result.digits,
            value=fast_result.value,
            variant_name="template_digits",
            confidence=fast_result.confidence,
            method="template",
            fallback_used=False,
            fast_reason=fast_result.reason,
        )

    current = recognize_prize_value_windows_only(image, debug_dir)
    detail_parts = []
    if current.fast_reason:
        detail_parts.append(current.fast_reason)
    if fast_result.reason:
        detail_parts.append(f"template={fast_result.reason}")
    return RecognitionResult(
        raw_text=current.raw_text,
        normalized_text=current.normalized_text,
        value=current.value,
        variant_name=current.variant_name,
        confidence=current.confidence if current.value is not None else fast_result.confidence,
        method=current.method if current.value is not None else ("template_failed" if fast_result.value is None else "template_low_confidence"),
        fallback_used=True,
        fast_reason="; ".join(detail_parts),
    )


def recognize_text(image: Image.Image, debug_dir: Path | None, prefix: str) -> TextRecognitionResult:
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
    best = TextRecognitionResult(raw_text="", normalized_text="", variant_name="none")

    for variant_name, variant in _render_variants(image):
        if debug_dir is not None:
            variant_path = debug_dir / f"{prefix}_{variant_name}.png"
            variant.save(variant_path)
        else:
            variant_path = _temp_variant_path(f"kg_{prefix}", variant_name)
            variant.save(variant_path)
        raw_text = _run_windows_ocr(variant_path)
        normalized = _normalize_text(raw_text)
        current = TextRecognitionResult(raw_text=raw_text, normalized_text=normalized, variant_name=variant_name)
        if normalized:
            return current
        best = current

    return best
