from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from app.config import AppConfig
from app.fast_ocr import PrefilterResult
from app.monitor import MonitorPhase, MonitorState, OcrStatus, PrizeMonitor
from app.recognition import RecognitionResult
from app.vision import AnchorStatus


def controlled_reading(value: int) -> RecognitionResult:
    return RecognitionResult(
        raw_text=str(value),
        normalized_text=str(value),
        value=value,
        variant_name="synthetic",
        confidence=1.0,
        method="rapidocr_ppocrv6_onnx",
        fallback_used=False,
        fast_reason=(
            "clean RapidOCR reading confirmed by PaddleOCR; "
            f"paddle={value} confidence=1.000000 reasons=backward_or_reset"
        ),
    )


def disagreement_reading() -> RecognitionResult:
    return RecognitionResult(
        raw_text="",
        normalized_text="",
        value=None,
        variant_name="synthetic",
        confidence=0.0,
        method="rapid_paddle_disagreement",
        fallback_used=False,
        fast_reason="RapidOCR and PaddleOCR disagree",
    )


def safe_anchors() -> AnchorStatus:
    crop = Image.new("RGB", (8, 8), "white")
    return AnchorStatus(
        event_screen_ok=True,
        button_visible=True,
        title_score=1.0,
        screen_anchor_score=1.0,
        button_score=1.0,
        gold_ratio=1.0,
        title_text="",
        button_text="",
        title_variant="test",
        button_variant="test",
        title_crop=crop,
        button_crop=crop,
    )


def neutral_prefilter() -> PrefilterResult:
    return PrefilterResult(
        status="synthetic",
        confidence=1.0,
        digit_count=5,
        first_digit=1,
        reason="isolated reset test",
        timings_ms={},
        possible_reset=False,
        raw_prefix="",
    )


class ConfirmedDecreaseResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.base = datetime(2026, 7, 16, 15, 0, 0)
        self.monitor = object.__new__(PrizeMonitor)
        self.monitor.config = AppConfig(
            runtime_dir=root,
            state_path=root / "state.json",
            reset_history_path=root / "production_reset_history.json",
            reset_diagnostics_dir=root / "reset_diagnostics",
        )
        self.monitor.state = MonitorState(
            phase=MonitorPhase.WAITING,
            ocr_status=OcrStatus.VISIBLE,
            reset_time_known=True,
            test_mode=True,
            real_mode_armed=False,
        )
        self.monitor.reset_history = []
        self.monitor.recent_observations = deque(maxlen=40)
        self.monitor._latest_screen = None
        self.monitor._latest_prize_crop = None
        self.monitor._save_reset_diagnostics = lambda *_args, **_kwargs: root / "diagnostic.json"
        self.monitor._save_persisted_state = lambda: None
        self.anchors = safe_anchors()
        self.prefilter = neutral_prefilter()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def begin_cycle(self, peak: int, seconds_since_reset: int = 121, baseline: int | None = None) -> None:
        self.monitor.state.last_reset_at = self.base - timedelta(seconds=seconds_since_reset)
        self.monitor.state.last_reset_confirmed_at = self.monitor.state.last_reset_at
        self.monitor.state.last_confirmed_prize = peak
        self.monitor.state.last_trusted_at = self.base - timedelta(milliseconds=200)
        self.monitor.state.peak_since_reset = peak
        self.monitor.state.post_reset_baseline = baseline
        self.monitor.state.reset_episode_locked = False
        self.monitor.state.reset_episode_token = 1
        self.monitor.state.last_recorded_reset_episode_token = None

    def frame(
        self,
        value: int | None,
        offset_ms: int,
        capture_id: str,
        *,
        notification: bool = False,
        disagreement: bool = False,
    ) -> None:
        now = self.base + timedelta(milliseconds=offset_ms)
        previous_trusted_at = self.monitor.state.last_trusted_at
        self.monitor.state.notification_veto = notification
        recognition = disagreement_reading() if disagreement else controlled_reading(value or 0)
        ocr_status = OcrStatus.OBSCURED if notification else OcrStatus.VISIBLE
        if disagreement:
            ocr_status = OcrStatus.ERROR
        trusted_value = None
        trust_reason = "OCR not visible"
        if value is not None and ocr_status == OcrStatus.VISIBLE:
            trusted_value, trust_reason = self.monitor._resolve_trusted_value(value, now)
        self.monitor.state.raw_ocr_value = recognition.value
        self.monitor.state.trusted_value = trusted_value
        self.monitor.state.last_trust_reason = trust_reason
        self.monitor.state.ocr_status = ocr_status

        if trusted_value is not None:
            self.monitor._update_peak_tracking(trusted_value, recognition)
            self.monitor._update_reset_episode_lock(trusted_value, now, capture_id)
        self.monitor._update_reset_detection(
            trusted_value,
            ocr_status,
            now,
            capture_id,
            previous_trusted_at,
            recognition,
            self.anchors,
            self.prefilter,
        )

    def assert_confirmed(self, peak: int, after: int) -> None:
        self.assertEqual(len(self.monitor.reset_history), 1)
        event = self.monitor.reset_history[0]
        self.assertEqual(event.peak_before_reset, peak)
        self.assertEqual(event.value_after_reset, after)
        self.assertEqual(self.monitor.state.phase, MonitorPhase.RESET_COOLDOWN)
        self.assertTrue(self.monitor.state.reset_episode_locked)

    def test_a_31250_to_16250_to_16300_confirms(self) -> None:
        self.begin_cycle(31_250)
        self.frame(16_250, 0, "low-1")
        self.frame(16_300, 200, "low-2")

        self.assert_confirmed(31_250, 16_300)
        event = self.monitor.reset_history[0]
        self.assertIn("15:00:00", event.reset_event_at or "")
        self.assertIn("15:00:00.200", event.reset_confirmed_at or "")

    def test_b_20000_to_10000_to_10050_confirms(self) -> None:
        self.begin_cycle(20_000)
        self.frame(10_000, 0, "low-1")
        self.frame(10_050, 200, "low-2")
        self.assert_confirmed(20_000, 10_050)

    def test_c_15000_to_13000_to_13050_confirms(self) -> None:
        self.begin_cycle(15_000)
        self.frame(13_000, 0, "low-1")
        self.frame(13_050, 200, "low-2")
        self.assert_confirmed(15_000, 13_050)

    def test_d_return_to_old_level_cancels_candidate(self) -> None:
        self.begin_cycle(15_000)
        self.frame(13_000, 0, "low-1")
        self.frame(15_100, 200, "low-2")

        self.assertEqual(self.monitor.reset_history, [])
        self.assertEqual(self.monitor.state.reset_candidate_hits, 0)

    def test_e_disagreement_after_first_low_cancels(self) -> None:
        self.begin_cycle(15_000)
        self.frame(14_950, 0, "low-1")
        self.frame(None, 200, "bad-2", disagreement=True)

        self.assertEqual(self.monitor.reset_history, [])
        self.assertEqual(self.monitor.state.reset_candidate_hits, 0)

    def test_f_90_second_interval_blocks_reset(self) -> None:
        self.begin_cycle(31_250, seconds_since_reset=90)
        self.frame(16_250, 0, "low-1")
        self.frame(16_300, 200, "low-2")

        self.assertEqual(self.monitor.reset_history, [])
        self.assertEqual(self.monitor.state.reset_candidate_hits, 0)
        self.assertEqual(self.monitor.state.last_confirmed_prize, 16_300)

    def test_g_15000_growth_unlocks_episode_after_120_seconds(self) -> None:
        self.begin_cycle(31_250, baseline=16_250)
        self.monitor.state.reset_episode_locked = True
        for index, value in enumerate((31_150, 31_200, 31_250), start=1):
            self.frame(value, index * 200, f"frame-{index}")

        self.assertFalse(self.monitor.state.reset_episode_locked)
        self.assertTrue(self.monitor.state.reset_new_cycle_confirmed)

    def test_h_2000_growth_does_not_lock_short_cycle_forever(self) -> None:
        self.begin_cycle(15_000, baseline=13_000)
        self.monitor.state.reset_episode_locked = True
        for index, value in enumerate((14_900, 14_950, 15_000), start=1):
            self.frame(value, index * 200, f"frame-{index}")

        self.assertFalse(self.monitor.state.reset_episode_locked)
        self.assertTrue(self.monitor.state.reset_new_cycle_confirmed)

    def test_i_notification_is_ignored_before_clean_low_candidate(self) -> None:
        self.begin_cycle(31_250)
        self.frame(None, 0, "notification", notification=True)
        self.frame(16_250, 200, "low-1")
        self.frame(16_300, 400, "low-2")

        self.assert_confirmed(31_250, 16_300)

    def test_duplicate_low_capture_cannot_confirm(self) -> None:
        self.begin_cycle(31_250)
        self.frame(16_250, 0, "same-capture")
        self.frame(16_300, 200, "same-capture")

        self.assertEqual(self.monitor.reset_history, [])
        self.assertEqual(self.monitor.state.reset_candidate_hits, 1)

    def test_second_value_below_first_low_restarts_candidate(self) -> None:
        self.begin_cycle(31_250)
        self.frame(16_250, 0, "low-1")
        self.frame(16_000, 200, "low-2")

        self.assertEqual(self.monitor.reset_history, [])
        self.assertEqual(self.monitor.state.reset_candidate_hits, 1)
        self.assertEqual(self.monitor.state.reset_first_low_value, 16_000)


if __name__ == "__main__":
    unittest.main()
