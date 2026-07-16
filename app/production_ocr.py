from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from app.recognition import extract_digit_roi


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "ocr_benchmark_py313"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))


@dataclass(frozen=True)
class EngineReading:
    engine: str
    text: str
    value: int | None
    confidence: float
    latency_ms: float


@dataclass(frozen=True)
class NotificationAssessment:
    direct_visible: bool
    heavy: bool
    veto: bool
    stage: str
    clear_streak: int
    dark_ratio: float


@dataclass(frozen=True)
class ProductionOcrResult:
    current: EngineReading | None
    rapid: EngineReading | None
    paddle: EngineReading | None
    notification: NotificationAssessment
    control_reasons: tuple[str, ...]
    recovered_after_notification: bool
    total_latency_ms: float
    reason: str


def _digits_value(text: str | None) -> int | None:
    digits = re.sub(r"\D", "", text or "")
    if len(digits) < 4:
        return None
    value = int(digits)
    return value if 0 < value <= 9_999_999 else None


def _prepared_roi(crop: Image.Image) -> Image.Image:
    roi = extract_digit_roi(crop)
    return roi.resize((roi.width * 4, roi.height * 4), Image.Resampling.LANCZOS)


def notification_dark_ratio(prize_crop: Image.Image) -> float:
    rgb = np.asarray(prize_crop.convert("RGB"), dtype=np.float32)
    brightness = rgb.mean(axis=2)
    return float((brightness < 65.0).mean())


class NotificationVetoTracker:
    """Latch a notification until its fade tail and two clean frames have passed."""

    def __init__(self, visible_dark_ratio: float = 0.15) -> None:
        self.visible_dark_ratio = visible_dark_ratio
        self.latched = False
        self.clear_streak = 0
        self.last_capture_id: str | None = None

    def observe(self, prize_crop: Image.Image, capture_id: str) -> NotificationAssessment:
        if capture_id == self.last_capture_id:
            return NotificationAssessment(False, False, self.latched, "duplicate_capture", self.clear_streak, 0.0)
        self.last_capture_id = capture_id
        dark_ratio = notification_dark_ratio(prize_crop)
        direct = dark_ratio >= self.visible_dark_ratio
        heavy = dark_ratio >= 0.30
        if direct:
            self.latched = True
            self.clear_streak = 0
            stage = "notification_heavy" if heavy else "notification_visible"
            return NotificationAssessment(True, heavy, True, stage, 0, dark_ratio)
        if not self.latched:
            return NotificationAssessment(False, False, False, "clean", 0, dark_ratio)

        self.clear_streak += 1
        if self.clear_streak == 1:
            stage = "notification_fade_guard"
        elif self.clear_streak == 2:
            stage = "clean_confirmation_1"
        else:
            stage = "clean_confirmation_2"
        return NotificationAssessment(False, False, True, stage, self.clear_streak, dark_ratio)

    def confirm_recovery(self) -> None:
        self.latched = False
        self.clear_streak = 0

    def reject_recovery(self) -> None:
        # Keep one guard frame so two new independent clean frames are required.
        self.latched = True
        self.clear_streak = 1


class ProductionOcrEngines:
    def __init__(self) -> None:
        self._rapid = None
        self._paddle = None
        self._lock = threading.Lock()

    def _rapid_engine(self):
        with self._lock:
            if self._rapid is None:
                from rapidocr import RapidOCR

                self._rapid = RapidOCR(
                    params={
                        "Global.use_det": False,
                        "Global.use_cls": False,
                        "Global.use_rec": True,
                        "Global.log_level": "error",
                    }
                )
            return self._rapid

    def _paddle_engine(self):
        with self._lock:
            if self._paddle is None:
                from paddleocr import TextRecognition

                self._paddle = TextRecognition(
                    model_name="PP-OCRv6_medium_rec",
                    engine="onnxruntime",
                    device="cpu",
                )
            return self._paddle

    def rapid(self, crop: Image.Image) -> EngineReading:
        roi = _prepared_roi(crop)
        started = time.perf_counter()
        result = self._rapid_engine()(np.asarray(roi), use_det=False, use_cls=False, use_rec=True)
        latency_ms = (time.perf_counter() - started) * 1000.0
        text = str(result.txts[0]) if result.txts else ""
        confidence = float(result.scores[0]) if result.scores else 0.0
        return EngineReading("rapidocr_ppocrv6_onnx", text, _digits_value(text), confidence, latency_ms)

    def paddle(self, crop: Image.Image) -> EngineReading:
        roi = _prepared_roi(crop)
        started = time.perf_counter()
        result = list(self._paddle_engine().predict(np.asarray(roi)))[0].json["res"]
        latency_ms = (time.perf_counter() - started) * 1000.0
        text = str(result.get("rec_text") or "")
        return EngineReading(
            "paddleocr_ppocrv6_onnx_control",
            text,
            _digits_value(text),
            float(result.get("rec_score", 0.0)),
            latency_ms,
        )

    def warm_up(self, crop: Image.Image) -> dict[str, float | int | str | None]:
        rapid_cold = self.rapid(crop)
        rapid_warm = self.rapid(crop)
        paddle_cold = self.paddle(crop)
        paddle_warm = self.paddle(crop)
        return {
            "rapid_value": rapid_warm.value,
            "paddle_value": paddle_warm.value,
            "rapid_cold_ms": round(rapid_cold.latency_ms, 3),
            "rapid_warm_ms": round(rapid_warm.latency_ms, 3),
            "paddle_cold_ms": round(paddle_cold.latency_ms, 3),
            "paddle_warm_ms": round(paddle_warm.latency_ms, 3),
        }


class ProductionOcrPipeline:
    def __init__(
        self,
        engines: ProductionOcrEngines | None = None,
        notification_tracker: NotificationVetoTracker | None = None,
        compatible_growth: int = 8_000,
    ) -> None:
        self.engines = engines or ProductionOcrEngines()
        self.notification_tracker = notification_tracker or NotificationVetoTracker()
        self.compatible_growth = compatible_growth
        self._pending_clean: EngineReading | None = None
        self._pending_capture_id: str | None = None

    def process(
        self,
        crop: Image.Image,
        capture_id: str,
        control_policy: Callable[[EngineReading], tuple[str, ...]] | None = None,
        recovery_allowed: bool = True,
    ) -> ProductionOcrResult:
        started = time.perf_counter()
        notification = self.notification_tracker.observe(crop, capture_id)
        if notification.veto and notification.stage not in {"clean_confirmation_1", "clean_confirmation_2"}:
            self._pending_clean = None
            self._pending_capture_id = None
            return ProductionOcrResult(
                None, None, None, notification, (), False,
                (time.perf_counter() - started) * 1000.0,
                "notification veto: OCR decision path disabled",
            )

        rapid = self.engines.rapid(crop)
        if notification.stage == "clean_confirmation_1":
            self._pending_clean = rapid
            self._pending_capture_id = capture_id
            return ProductionOcrResult(
                None, rapid, None, notification, ("notification_recovery",), False,
                (time.perf_counter() - started) * 1000.0,
                "first clean frame stored; trusted tracking remains vetoed",
            )

        if notification.stage == "clean_confirmation_2":
            if not recovery_allowed:
                self.notification_tracker.reject_recovery()
                self._pending_clean = None
                self._pending_capture_id = None
                return ProductionOcrResult(
                    None, rapid, None, notification, ("notification_recovery",), False,
                    (time.perf_counter() - started) * 1000.0,
                    "notification recovery blocked by screen/button safety anchors",
                )
            pending = self._pending_clean
            independent = self._pending_capture_id is not None and self._pending_capture_id != capture_id
            compatible = (
                independent
                and pending is not None
                and pending.value is not None
                and rapid.value is not None
                and 0 <= rapid.value - pending.value <= self.compatible_growth
            )
            paddle = self.engines.paddle(crop)
            agreed = compatible and paddle.value is not None and paddle.value == rapid.value
            if agreed:
                self.notification_tracker.confirm_recovery()
                self._pending_clean = None
                self._pending_capture_id = None
                return ProductionOcrResult(
                    rapid, rapid, paddle, notification, ("notification_recovery",), True,
                    (time.perf_counter() - started) * 1000.0,
                    "two independent clean RapidOCR readings confirmed by PaddleOCR",
                )
            self.notification_tracker.reject_recovery()
            self._pending_clean = None
            self._pending_capture_id = None
            return ProductionOcrResult(
                None, rapid, paddle, notification, ("notification_recovery",), False,
                (time.perf_counter() - started) * 1000.0,
                "notification recovery disagreement; trusted tracking remains vetoed",
            )

        reasons = control_policy(rapid) if control_policy is not None else ()
        paddle = self.engines.paddle(crop) if reasons else None
        if paddle is not None and (rapid.value is None or paddle.value != rapid.value):
            return ProductionOcrResult(
                None, rapid, paddle, notification, reasons, False,
                (time.perf_counter() - started) * 1000.0,
                "RapidOCR/PaddleOCR disagreement; trusted value unchanged",
            )
        return ProductionOcrResult(
            rapid, rapid, paddle, notification, reasons, False,
            (time.perf_counter() - started) * 1000.0,
            "clean RapidOCR reading" + (" confirmed by PaddleOCR" if paddle else ""),
        )
