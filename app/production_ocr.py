from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass, replace
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


def digit_visibility(prize_crop: Image.Image) -> tuple[bool, bool]:
    """Check glyph-area contamination, not darkness of the whole notification bar.

    The supported game profile has warm yellow digits. White notification text
    and cool reward icons are independent reasons to reject an obscured frame.
    Small edge fragments are tolerated only with dual-engine OCR control.
    """
    rgb = np.asarray(extract_digit_roi(prize_crop), dtype=np.float32)
    if min(rgb.shape[:2]) < 10:
        return False, True
    rgb = rgb[3:-3, 3:-3]
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    white = (rgb.min(axis=2) > 150) & (rgb.max(axis=2) - rgb.min(axis=2) < 30)
    cool = ((blue > red + 15) | (green > red + 25)) & (rgb.max(axis=2) > 90)
    yellow = (red > 90) & (green > 70) & (red - blue > 25) & (green - blue > 20)
    obscured = white.mean() > 0.05 or cool.mean() > 0.01 or yellow.sum() < 40
    edge_content = bool(white.any() or cool.any())
    return not obscured, edge_content


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
        visible, edge_content = digit_visibility(prize_crop)
        direct = dark_ratio >= self.visible_dark_ratio or edge_content or not visible
        heavy = dark_ratio >= 0.30
        if not visible:
            self.latched = True
            self.clear_streak = 0
            stage = "notification_heavy" if heavy else "notification_visible"
            return NotificationAssessment(True, heavy, True, stage, 0, dark_ratio)
        if not self.latched:
            stage = "readable_notification" if direct else "clean"
            return NotificationAssessment(direct, heavy, False, stage, 0, dark_ratio)

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
        self._inference_lock = threading.RLock()

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
                        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
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
                    engine_config={"intra_op_num_threads": 2, "inter_op_num_threads": 1},
                )
            return self._paddle

    def rapid(self, crop: Image.Image) -> EngineReading:
        roi = _prepared_roi(crop)
        started = time.perf_counter()
        with self._inference_lock:
            result = self._rapid_engine()(np.asarray(roi), use_det=False, use_cls=False, use_rec=True)
        latency_ms = (time.perf_counter() - started) * 1000.0
        text = str(result.txts[0]) if result.txts else ""
        confidence = float(result.scores[0]) if result.scores else 0.0
        return EngineReading("rapidocr_ppocrv6_onnx", text, _digits_value(text), confidence, latency_ms)

    def paddle(self, crop: Image.Image) -> EngineReading:
        roi = _prepared_roi(crop)
        started = time.perf_counter()
        with self._inference_lock:
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
        frame_local_control: bool = False,
    ) -> ProductionOcrResult:
        started = time.perf_counter()
        notification = self.notification_tracker.observe(crop, capture_id)
        if notification.stage == "duplicate_capture":
            return ProductionOcrResult(
                None, None, None, notification, (), False,
                (time.perf_counter() - started) * 1000.0,
                "duplicate capture ignored; recovery still requires a new frame",
            )
        if frame_local_control:
            if not digit_visibility(crop)[0] or not recovery_allowed:
                return ProductionOcrResult(None,None,None,notification,(),False,
                    (time.perf_counter()-started)*1000.0,"video frame obscured or anchors unavailable")
            rapid = self.engines.rapid(crop)
            paddle = self.engines.paddle(crop)
            agreed = (rapid.value is not None and rapid.value == paddle.value
                      and min(rapid.confidence,paddle.confidence) >= .90)
            if not agreed:
                return ProductionOcrResult(None,rapid,paddle,notification,("video_frame_control",),False,
                    (time.perf_counter()-started)*1000.0,"RapidOCR/PaddleOCR disagreement on video frame")
            was_latched = self.notification_tracker.latched
            self.notification_tracker.confirm_recovery()
            self._pending_clean = self._pending_capture_id = None
            notification = replace(notification,veto=False,stage="video_frame_visible",clear_streak=0)
            return ProductionOcrResult(rapid,rapid,paddle,notification,("video_frame_control",),was_latched,
                (time.perf_counter()-started)*1000.0,"visible video frame confirmed by PaddleOCR")
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
            agreed = (
                compatible and paddle.value is not None and paddle.value == rapid.value
                and pending.confidence >= 0.90 and rapid.confidence >= 0.90
                and paddle.confidence >= 0.90
            )
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
        if notification.stage == "readable_notification":
            reasons = (*reasons, "digit_visibility_control")
        paddle = self.engines.paddle(crop) if reasons else None
        visibility_confidence_ok = (
            notification.stage != "readable_notification"
            or (paddle is not None and rapid.confidence >= 0.90 and paddle.confidence >= 0.90)
        )
        if paddle is not None and (rapid.value is None or paddle.value != rapid.value or not visibility_confidence_ok):
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
