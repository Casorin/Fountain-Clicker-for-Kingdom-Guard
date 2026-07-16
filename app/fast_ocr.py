from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps


@dataclass(frozen=True)
class DigitTemplate:
    digit: str
    sample_id: str
    array: np.ndarray
    source_path: str


@dataclass(frozen=True)
class FastOcrResult:
    value: int | None
    confidence: float
    method: str
    digits: str
    reason: str
    segmentation_count: int


@dataclass(frozen=True)
class PrefilterResult:
    status: str
    confidence: float
    digit_count: int | None
    first_digit: int | None
    reason: str
    timings_ms: dict[str, float]
    possible_reset: bool
    raw_prefix: str


@lru_cache(maxsize=1)
def load_digit_templates(manifest_path: str) -> dict[str, list[DigitTemplate]]:
    path = Path(manifest_path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    templates: dict[str, list[DigitTemplate]] = {str(d): [] for d in range(10)}
    for row in data.get("templates", []):
        digit = str(row["digit"])
        image_path = path.parent / row["file"]
        image = Image.open(image_path).convert("L")
        array = np.array(image, dtype=np.float32) / 255.0
        templates.setdefault(digit, []).append(
            DigitTemplate(
                digit=digit,
                sample_id=row["sample_id"],
                array=array,
                source_path=row["source_path"],
            )
        )
    return {digit: items for digit, items in templates.items() if items}


def clear_template_cache() -> None:
    load_digit_templates.cache_clear()


def preprocess_prize_crop(image: Image.Image, scale: int = 4) -> tuple[Image.Image, np.ndarray]:
    digit_region_left = int(image.width * 0.22)
    # Skip the "Призовой фонд" label line and keep only the numeric band.
    digit_region_top = int(image.height * 0.28)
    cropped_rgb = image.crop((digit_region_left, digit_region_top, image.width, image.height)).convert("RGB")
    enlarged_rgb = cropped_rgb.resize((cropped_rgb.width * scale, cropped_rgb.height * scale), Image.Resampling.LANCZOS)
    sharpened_rgb = enlarged_rgb.filter(ImageFilter.SHARPEN)
    contrast_rgb = ImageOps.autocontrast(sharpened_rgb)
    contrast = ImageOps.grayscale(contrast_rgb)
    arr = np.array(contrast, dtype=np.uint8)
    rgb = np.array(contrast_rgb, dtype=np.uint8)
    brightness = rgb.mean(axis=2)
    channel_spread = rgb.max(axis=2) - rgb.min(axis=2)
    threshold = _otsu_threshold(arr)
    threshold = max(135, min(205, threshold))
    white_mask = (brightness >= 150) & (channel_spread <= 70)
    binary = white_mask | (arr >= threshold)
    # If the mask is too sparse, ease the grayscale threshold a bit.
    if binary.mean() < 0.03:
        binary = white_mask | (arr >= max(120, threshold - 12))
    # Keep only the bright digit region, not the dark panel edges.
    return contrast, _trim_empty_rows(binary)


def segment_digits(binary: np.ndarray, max_components: int | None = None) -> list[np.ndarray]:
    if binary.size == 0:
        return []
    raw_component_limit = max_components * 4 if max_components is not None else None
    components = _connected_components(binary, limit=raw_component_limit)
    if not components:
        return []
    if raw_component_limit is not None and len(components) > raw_component_limit:
        return []
    height = binary.shape[0]
    filtered = [
        comp
        for comp in components
        if comp["area"] >= 24
        and comp["height"] >= int(height * 0.38)
        and comp["height"] <= int(height * 0.82)
        and comp["width"] >= 6
    ]
    if max_components is not None and len(filtered) > max_components:
        return []
    filtered.sort(key=lambda item: item["left"])
    base_width = float(np.median([item["width"] for item in filtered])) if filtered else 0.0
    pieces: list[np.ndarray] = []
    for item in filtered:
        expected_parts = 1
        if base_width > 0:
            expected_parts = max(1, int(round(item["width"] / base_width)))
        pieces.extend(_split_component_by_projection(item["image"], expected_parts=expected_parts))
    pieces = [piece for piece in pieces if piece.shape[1] >= 6 and piece.shape[0] >= int(height * 0.38)]
    return _drop_leading_noise(pieces)


def normalize_digit_image(binary_digit: np.ndarray, size: tuple[int, int] = (24, 36)) -> np.ndarray:
    digit = Image.fromarray((binary_digit.astype(np.uint8) * 255), mode="L")
    padded = ImageOps.expand(digit, border=4, fill=0)
    resized = padded.resize(size, Image.Resampling.NEAREST)
    return np.array(resized, dtype=np.float32) / 255.0


def recognize_digits_from_templates(
    image: Image.Image,
    template_manifest_path: Path,
    confidence_threshold: float,
) -> FastOcrResult:
    templates = load_digit_templates(str(template_manifest_path))
    if not templates:
        return FastOcrResult(
            value=None,
            confidence=0.0,
            method="template_unavailable",
            digits="",
            reason="digit templates are unavailable",
            segmentation_count=0,
        )

    _processed, binary = preprocess_prize_crop(image)
    digit_masks = segment_digits(binary)
    if not digit_masks:
        return FastOcrResult(
            value=None,
            confidence=0.0,
            method="template_failed",
            digits="",
            reason="digit segmentation failed",
            segmentation_count=0,
        )
    if len(digit_masks) > 6:
        return FastOcrResult(
            value=None,
            confidence=0.0,
            method="template_failed",
            digits="",
            reason=f"too many digit segments: {len(digit_masks)}",
            segmentation_count=len(digit_masks),
        )

    digits: list[str] = []
    confidences: list[float] = []
    reasons: list[str] = []
    for mask in digit_masks:
        normalized = normalize_digit_image(mask)
        best_digit = ""
        best_score = -1.0
        second_score = -1.0
        for digit, examples in templates.items():
            score = max(_template_similarity(normalized, sample.array) for sample in examples)
            if score > best_score:
                second_score = best_score
                best_score = score
                best_digit = digit
            elif score > second_score:
                second_score = score
        if not best_digit:
            return FastOcrResult(
                value=None,
                confidence=0.0,
                method="template_failed",
                digits="",
                reason="no template match",
                segmentation_count=len(digit_masks),
            )
        gap = max(0.0, best_score - max(second_score, 0.0))
        digit_confidence = max(0.0, min(1.0, best_score * 0.75 + gap * 1.25))
        digits.append(best_digit)
        confidences.append(digit_confidence)
        reasons.append(f"{best_digit}:{best_score:.3f}/{second_score:.3f}")

    joined = "".join(digits)
    if len(joined) not in {5, 6}:
        return FastOcrResult(
            value=None,
            confidence=min(confidences) if confidences else 0.0,
            method="template_failed",
            digits=joined,
            reason="recognized unsupported digit count",
            segmentation_count=len(digit_masks),
        )

    confidence = min(confidences) * 0.6 + float(np.mean(confidences)) * 0.4
    try:
        value = int(joined)
    except ValueError:
        return FastOcrResult(
            value=None,
            confidence=0.0,
            method="template_failed",
            digits=joined,
            reason="int parse failed",
            segmentation_count=len(digit_masks),
        )

    method = "template" if confidence >= confidence_threshold else "template_low_confidence"
    return FastOcrResult(
        value=value,
        confidence=confidence,
        method=method,
        digits=joined,
        reason="; ".join(reasons),
        segmentation_count=len(digit_masks),
    )


def prefilter_range(
    image: Image.Image,
    template_manifest_path: Path,
    confidence_threshold: float,
    previous_reliable_value: int | None = None,
    reset_min_trusted_value: int = 100_000,
    max_components: int = 8,
) -> PrefilterResult:
    timings: dict[str, float] = {}
    started = _now()
    _processed, binary = preprocess_prize_crop(image)
    timings["preprocess"] = _elapsed_ms(started)
    # Keep an early noise reject, but do not classify ordinary bright five-digit
    # crops as uncertain too aggressively.
    if binary.mean() > 0.90:
        return PrefilterResult("UNCERTAIN", 0.0, None, None, "binary mask too dense", timings, False, "")

    started = _now()
    digit_masks = segment_digits(binary, max_components=max_components)
    timings["segment"] = _elapsed_ms(started)
    digit_count = len(digit_masks)
    if digit_count == 0:
        return PrefilterResult("UNCERTAIN", 0.0, None, None, "no digit segments", timings, False, "")
    if digit_count > max_components:
        return PrefilterResult("UNCERTAIN", 0.0, digit_count, None, f"too many digit segments: {digit_count}", timings, False, "")
    if digit_count <= 4 or digit_count > 6:
        possible_reset = (
            previous_reliable_value is not None
            and previous_reliable_value >= reset_min_trusted_value
            and digit_count <= 5
        )
        return PrefilterResult("UNCERTAIN", 0.0, digit_count, None, "unsupported digit count", timings, possible_reset, "")
    if digit_count == 5:
        widths = [mask.shape[1] for mask in digit_masks]
        median_width = float(np.median(widths)) if widths else 0.0
        # A very wide component often means two zeros merged into one shape,
        # which is exactly the dangerous case for 200000-500000 targets.
        if median_width > 0 and max(widths) >= median_width * 2.10:
            possible_reset = previous_reliable_value is not None and previous_reliable_value >= reset_min_trusted_value
            return PrefilterResult(
                "UNCERTAIN",
                0.45,
                digit_count,
                None,
                "possible merged digits in five-digit count",
                timings,
                possible_reset,
                "",
            )
        possible_reset = previous_reliable_value is not None and previous_reliable_value >= reset_min_trusted_value
        return PrefilterResult("BELOW_RANGE", 0.99, digit_count, None, "five-digit value", timings, possible_reset, "")

    # Six digits: only classify the first digit.
    templates = load_digit_templates(str(template_manifest_path))
    if not templates:
        return PrefilterResult("UNCERTAIN", 0.0, digit_count, None, "digit templates unavailable", timings, False, "")

    started = _now()
    normalized = normalize_digit_image(digit_masks[0])
    best_digit = None
    best_score = -1.0
    second_score = -1.0
    for digit, examples in templates.items():
        score = max(_template_similarity(normalized, sample.array) for sample in examples)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_digit = int(digit)
        elif score > second_score:
            second_score = score
    timings["first_digit_match"] = _elapsed_ms(started)

    if best_digit is None:
        return PrefilterResult("UNCERTAIN", 0.0, digit_count, None, "first digit match failed", timings, False, "")

    gap = max(0.0, best_score - max(second_score, 0.0))
    confidence = max(0.0, min(1.0, best_score * 0.7 + gap * 1.4))
    if confidence < confidence_threshold:
        return PrefilterResult("UNCERTAIN", confidence, digit_count, best_digit, "low first-digit confidence", timings, False, str(best_digit))

    if best_digit in {2, 3, 4, 5}:
        return PrefilterResult(
            "POSSIBLE_TARGET",
            confidence,
            digit_count,
            best_digit,
            "six-digit leading 2-5",
            timings,
            False,
            str(best_digit),
        )
    if best_digit == 1:
        return PrefilterResult("BELOW_RANGE", confidence, digit_count, best_digit, "six-digit leading 1", timings, False, str(best_digit))
    return PrefilterResult("ABOVE_RANGE", confidence, digit_count, best_digit, "six-digit leading 6-9", timings, False, str(best_digit))


def _trim_empty_rows(binary: np.ndarray) -> np.ndarray:
    row_sums = binary.sum(axis=1)
    rows = np.where(row_sums > 0)[0]
    if len(rows) == 0:
        return binary
    top = max(0, int(rows[0]) - 2)
    bottom = min(binary.shape[0], int(rows[-1]) + 3)
    return binary[top:bottom, :]


def _now() -> float:
    import time

    return time.perf_counter()


def _elapsed_ms(started: float) -> float:
    import time

    return (time.perf_counter() - started) * 1000


def _otsu_threshold(arr: np.ndarray) -> int:
    hist, _ = np.histogram(arr.ravel(), bins=256, range=(0, 256))
    total = arr.size
    sum_total = float(np.dot(np.arange(256), hist))
    sum_background = 0.0
    weight_background = 0.0
    max_variance = -1.0
    threshold = 127
    for idx in range(256):
        weight_background += hist[idx]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += idx * hist[idx]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_total - sum_background) / weight_foreground
        variance = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if variance > max_variance:
            max_variance = variance
            threshold = idx
    return threshold


def _connected_components(binary: np.ndarray, limit: int | None = None) -> list[dict[str, object]]:
    height, width = binary.shape
    visited = np.zeros_like(binary, dtype=bool)
    components: list[dict[str, object]] = []
    for y in range(height):
        for x in range(width):
            if not binary[y, x] or visited[y, x]:
                continue
            stack = [(y, x)]
            visited[y, x] = True
            pixels: list[tuple[int, int]] = []
            min_x = max_x = x
            min_y = max_y = y
            while stack:
                cy, cx = stack.pop()
                pixels.append((cy, cx))
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                for ny in range(max(0, cy - 1), min(height, cy + 2)):
                    for nx in range(max(0, cx - 1), min(width, cx + 2)):
                        if binary[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((ny, nx))
            component = np.zeros((max_y - min_y + 1, max_x - min_x + 1), dtype=bool)
            for py, px in pixels:
                component[py - min_y, px - min_x] = True
            components.append(
                {
                    "left": min_x,
                    "top": min_y,
                    "width": max_x - min_x + 1,
                    "height": max_y - min_y + 1,
                    "area": len(pixels),
                    "image": component,
                }
            )
            if limit is not None and len(components) > limit:
                return components
    return components


def _split_component_by_projection(component: np.ndarray, expected_parts: int = 1) -> list[np.ndarray]:
    parts = [component]
    changed = True
    while changed:
        changed = False
        next_parts: list[np.ndarray] = []
        for part in parts:
            local_expected = max(1, int(round(expected_parts / max(1, len(parts)))))
            split_parts = _split_once(part, expected_parts=local_expected)
            if len(split_parts) > 1:
                changed = True
            next_parts.extend(split_parts)
        parts = next_parts
    return parts


def _split_once(component: np.ndarray, expected_parts: int = 1) -> list[np.ndarray]:
    height, width = component.shape
    if width < 30 and expected_parts <= 1:
        return [component]
    col_sums = component.sum(axis=0)
    threshold = max(1, int(height * 0.10))
    candidate_columns = np.where(col_sums <= threshold)[0]
    if len(candidate_columns) == 0:
        return [component]
    groups: list[tuple[int, int]] = []
    start = int(candidate_columns[0])
    prev = int(candidate_columns[0])
    for column in candidate_columns[1:]:
        column = int(column)
        if column == prev + 1:
            prev = column
            continue
        groups.append((start, prev))
        start = column
        prev = column
    groups.append((start, prev))

    for start, end in groups:
        cut = (start + end) // 2
        left = component[:, :cut]
        right = component[:, cut + 1 :]
        if left.shape[1] < 8 or right.shape[1] < 8:
            continue
        left = _trim_empty_columns(left)
        right = _trim_empty_columns(right)
        if left.shape[1] < 8 or right.shape[1] < 8:
            continue
        return [left, right]
    if expected_parts > 1:
        cuts: list[int] = []
        for part_index in range(1, expected_parts):
            target = int(round(width * part_index / expected_parts))
            left = max(6, target - max(3, width // 12))
            right = min(width - 6, target + max(3, width // 12))
            if left >= right:
                continue
            window = col_sums[left:right]
            cut = left + int(np.argmin(window))
            cuts.append(cut)
        if cuts:
            segments: list[np.ndarray] = []
            start = 0
            for cut in cuts + [width]:
                piece = component[:, start:cut]
                piece = _trim_empty_columns(piece)
                if piece.shape[1] >= 8:
                    segments.append(piece)
                start = cut
            if len(segments) > 1:
                return segments
    return [component]


def _trim_empty_columns(component: np.ndarray) -> np.ndarray:
    col_sums = component.sum(axis=0)
    cols = np.where(col_sums > 0)[0]
    if len(cols) == 0:
        return component
    left = int(cols[0])
    right = int(cols[-1]) + 1
    return component[:, left:right]


def _drop_leading_noise(pieces: list[np.ndarray]) -> list[np.ndarray]:
    if len(pieces) < 6:
        return pieces
    widths = [piece.shape[1] for piece in pieces]
    if len(widths) < 2:
        return pieces
    median_rest = float(np.median(widths[1:]))
    if median_rest <= 0:
        return pieces
    if widths[0] <= median_rest * 0.72:
        return pieces[1:]
    return pieces


def _template_similarity(lhs: np.ndarray, rhs: np.ndarray) -> float:
    intersection = float(np.logical_and(lhs >= 0.5, rhs >= 0.5).sum())
    union = float(np.logical_or(lhs >= 0.5, rhs >= 0.5).sum())
    iou = intersection / union if union else 0.0
    mse = float(np.mean((lhs - rhs) ** 2))
    return max(0.0, min(1.0, iou * 0.8 + (1.0 - mse) * 0.2))
