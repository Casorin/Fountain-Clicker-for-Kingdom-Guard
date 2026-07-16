from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from app.capture import crop_rect
from app.config import AppConfig
from app.recognition import TextRecognitionResult, recognize_text


@dataclass(frozen=True)
class AnchorStatus:
    event_screen_ok: bool
    button_visible: bool
    title_score: float
    screen_anchor_score: float
    button_score: float
    gold_ratio: float
    title_text: str
    button_text: str
    title_variant: str
    button_variant: str
    title_crop: Image.Image
    button_crop: Image.Image


def _prepare_for_match(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.convert("L").resize(size, Image.Resampling.LANCZOS)


def _similarity_score(reference: Image.Image, current: Image.Image) -> float:
    lhs = _prepare_for_match(reference, (reference.width, reference.height))
    rhs = _prepare_for_match(current, (reference.width, reference.height))
    diff = ImageChops.difference(lhs, rhs)
    stat = ImageStat.Stat(diff)
    rms = math.sqrt(sum(value * value for value in stat.rms) / len(stat.rms))
    score = 1.0 - (rms / 255.0)
    return max(0.0, min(1.0, score))


def _load_template(path: Path) -> Image.Image:
    if not path.exists():
        raise FileNotFoundError(f"Не найден шаблон: {path}")
    return Image.open(path).convert("RGB")


def _gold_ratio(image: Image.Image) -> float:
    gold_pixels = 0
    total = image.width * image.height
    for red, green, blue in image.getdata():
        if red >= 170 and 110 <= green <= 210 and blue <= 120:
            gold_pixels += 1
    return gold_pixels / max(1, total)


def analyze_anchors(image: Image.Image, config: AppConfig, debug_dir: Path | None) -> AnchorStatus:
    return analyze_anchors_with_options(image, config, debug_dir, ocr_text=False)


def analyze_anchors_with_options(
    image: Image.Image,
    config: AppConfig,
    debug_dir: Path | None,
    ocr_text: bool = False,
) -> AnchorStatus:
    title_crop = crop_rect(image, config.event_title_crop)
    button_crop = crop_rect(image, config.button_crop)
    screen_anchor_crop = crop_rect(image, config.screen_anchor_crop)

    title_reference = _load_template(config.title_template_path)
    screen_anchor_reference = _load_template(config.screen_anchor_template_path)
    button_reference = _load_template(config.button_template_path)

    title_score = _similarity_score(title_reference, title_crop)
    screen_anchor_score = _similarity_score(screen_anchor_reference, screen_anchor_crop)
    button_score = _similarity_score(button_reference, button_crop)
    gold_ratio = _gold_ratio(button_crop)

    if ocr_text:
        title_text_result: TextRecognitionResult = recognize_text(title_crop, debug_dir, "title")
        button_text_result: TextRecognitionResult = recognize_text(button_crop, debug_dir, "button")
    else:
        title_text_result = TextRecognitionResult(raw_text="", normalized_text="", variant_name="skipped")
        button_text_result = TextRecognitionResult(raw_text="", normalized_text="", variant_name="skipped")

    event_screen_ok = (
        screen_anchor_score >= config.screen_anchor_threshold
        or title_score >= config.title_match_threshold
    )
    button_visible = (
        button_score >= config.button_match_threshold
        and gold_ratio >= config.button_gold_ratio_threshold
    )

    return AnchorStatus(
        event_screen_ok=event_screen_ok,
        button_visible=button_visible,
        title_score=title_score,
        screen_anchor_score=screen_anchor_score,
        button_score=button_score,
        gold_ratio=gold_ratio,
        title_text=title_text_result.normalized_text,
        button_text=button_text_result.normalized_text,
        title_variant=title_text_result.variant_name,
        button_variant=button_text_result.variant_name,
        title_crop=title_crop,
        button_crop=button_crop,
    )
