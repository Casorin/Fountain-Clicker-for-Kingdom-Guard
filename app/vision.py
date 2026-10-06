from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from app.capture import crop_rect
from app.config import AppConfig


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
    continuation_screen_ok: bool = False


def _text_mask(image: Image.Image, dark: bool, warm: bool = False) -> np.ndarray:
    rgb = np.asarray(image.convert('RGB'), dtype=np.int16)
    if warm:
        return (rgb[:, :, 0] > 200) & (rgb[:, :, 1] > 180) & (rgb[:, :, 2] < 190) & (rgb[:, :, 0] - rgb[:, :, 2] > 50)
    if dark:
        return (rgb[:, :, 0] < 190) & (rgb[:, :, 1] < 160) & (rgb[:, :, 2] < 110)
    return (rgb.min(axis=2) >= 215) & (rgb.max(axis=2) - rgb.min(axis=2) <= 40)


@lru_cache(maxsize=12)
def _reference_mask(path: str, modified: int, dark: bool, warm: bool) -> np.ndarray:
    with Image.open(path) as image:
        return _text_mask(image, dark, warm)


def _text_score(path: Path, image: Image.Image, dark: bool = False, warm: bool = False) -> float:
    try:
        expected = _reference_mask(str(path.resolve()), path.stat().st_mtime_ns, dark, warm)
    except (OSError, ValueError):
        return 0.0
    observed = _text_mask(image, dark, warm)
    if expected.shape != observed.shape or np.count_nonzero(expected) < 100:
        return 0.0
    return float(np.count_nonzero(expected & observed) / max(1, np.count_nonzero(expected | observed)))


def analyze_anchors(image: Image.Image, config: AppConfig, debug_dir: Path | None) -> AnchorStatus:
    return analyze_anchors_with_options(image, config, debug_dir)


def analyze_anchors_with_options(image: Image.Image, config: AppConfig,
                                debug_dir: Path | None, ocr_text: bool = False) -> AnchorStatus:
    prize = crop_rect(image, config.prize_label_crop)
    daily = crop_rect(image, config.daily_label_crop)
    reward = crop_rect(image, config.reward_label_crop)
    wish = crop_rect(image, config.wish_label_crop)
    button = crop_rect(image, config.button_crop)
    prize_score = _text_score(config.layout_template_dir / 'prize.png', prize)
    daily_score = _text_score(config.layout_template_dir / 'daily.png', daily)
    reward_score = _text_score(config.layout_template_dir / 'reward.png', reward, warm=True)
    button_score = max(_text_score(config.layout_template_dir / filename, wish, dark=True)
                       for filename in ('wish.png', 'wish_pressed.png', 'wish_infinitive.png', 'wish_infinitive_pressed.png'))
    pixels = np.asarray(button)
    gold = (pixels[:, :, 0] >= 170) & (pixels[:, :, 1] >= 110) & (pixels[:, :, 1] <= 210) & (pixels[:, :, 2] <= 120)
    gold_ratio = float(gold.mean())
    supported_size = image.size == (1080, 1080)
    # Season names/art never authorize input. Require two fixed interface labels
    # and separately require the actual wish button at the configured tap location.
    screen_ok = supported_size and min(prize_score, daily_score) >= config.layout_text_threshold
    button_ok = supported_size and button_score >= config.layout_text_threshold and gold_ratio >= config.button_gold_ratio_threshold
    return AnchorStatus(
        screen_ok, button_ok, daily_score, prize_score, button_score, gold_ratio,
        'Призовой фонд / Получено сегодня' if screen_ok else '',
        'ЗАГАДАЙТЕ ЖЕЛАНИЕ' if button_ok else '',
        'season_independent' if supported_size else 'unsupported_resolution',
        'wish_text', crop_rect(image, config.event_title_crop), button,
        supported_size and max(daily_score, reward_score) >= config.layout_text_threshold and button_ok,
    )
