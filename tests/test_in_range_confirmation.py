from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from app.config import AppConfig
from app.fast_ocr import PrefilterResult
from app.monitor import MonitorPhase, MonitorState, OcrStatus, PrizeMonitor
from app.persistence import UserRangeConfig
from app.recognition import RecognitionResult
from app.vision import AnchorStatus


class FakeAdb:
    def __init__(self) -> None:
        self.tap_calls: list[tuple[int, int]] = []

    def tap_persistent(self, x: int, y: int) -> None:
        self.tap_calls.append((x, y))


def anchors(screen_ok: bool = True, button_ok: bool = True) -> AnchorStatus:
    crop = Image.new("RGB", (8, 8), "white")
    return AnchorStatus(
        event_screen_ok=screen_ok,
        button_visible=button_ok,
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


def recognition(value: int = 123_500) -> RecognitionResult:
    return RecognitionResult(
        raw_text=str(value),
        normalized_text=str(value),
        value=value,
        variant_name="synthetic",
        confidence=1.0,
        method="rapidocr_ppocrv6_onnx",
        fallback_used=False,
    )


class InRangeConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.now = datetime(2026, 7, 16, 12, 0, 0)
        self.monitor = object.__new__(PrizeMonitor)
        self.monitor.config = AppConfig(
            runtime_dir=root,
            state_path=root / "state.json",
            reset_history_path=root / "production_reset_history.json",
            user_config_path=root / "user_config.json",
            debug_dir=root / "debug",
            trigger_dir=root / "triggers",
            test_mode_min_prize=100_000,
            test_mode_max_prize=200_000,
        )
        self.monitor.state = MonitorState(
            phase=MonitorPhase.WAITING,
            ocr_status=OcrStatus.VISIBLE,
            reset_time_known=True,
            test_mode=True,
            real_mode_armed=False,
        )
        self.monitor.user_range = UserRangeConfig(100_000, 200_000)
        self.monitor.tap_decisions_enabled = True
        self.monitor.adb = FakeAdb()
        self.monitor._now_provider = lambda: self.now
        self.monitor._latest_capture_completed_at = self.now
        self.monitor._save_trigger_diagnostics = lambda *_args, **_kwargs: None

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def observe(
        self,
        value: int,
        capture_id: str,
        offset_ms: int,
        frame_anchors: AnchorStatus | None = None,
    ) -> None:
        observed_at = self.now + timedelta(milliseconds=offset_ms)
        self.monitor._update_candidate(
            value,
            capture_id,
            observed_at,
            frame_anchors or anchors(),
        )

    def test_growing_values_on_independent_frames_confirm(self) -> None:
        self.observe(123_000, "frame-1", 0)
        self.observe(123_500, "frame-2", 200)

        self.assertEqual(self.monitor.state.phase, MonitorPhase.CONFIRMED)
        self.assertEqual(self.monitor.state.candidate_hits, 2)

    def test_duplicate_capture_does_not_confirm(self) -> None:
        self.observe(123_000, "frame-1", 0)
        self.observe(123_500, "frame-1", 200)

        self.assertEqual(self.monitor.state.phase, MonitorPhase.CANDIDATE)
        self.assertEqual(self.monitor.state.candidate_hits, 1)

    def test_backward_value_resets_candidate(self) -> None:
        self.observe(123_000, "frame-1", 0)
        self.observe(119_000, "frame-2", 200)

        self.assertEqual(self.monitor.state.phase, MonitorPhase.WAITING)
        self.assertEqual(self.monitor.state.candidate_hits, 0)

    def test_out_of_range_value_resets_candidate(self) -> None:
        self.observe(123_000, "frame-1", 0)
        self.observe(201_000, "frame-2", 200)

        self.assertEqual(self.monitor.state.phase, MonitorPhase.WAITING)
        self.assertEqual(self.monitor.state.candidate_hits, 0)

    def test_notification_veto_resets_candidate(self) -> None:
        self.observe(123_000, "frame-1", 0)
        self.monitor.state.notification_veto = True
        self.observe(123_500, "frame-2", 200)

        self.assertEqual(self.monitor.state.phase, MonitorPhase.WAITING)
        self.assertEqual(self.monitor.state.candidate_hits, 0)
        self.assertFalse(self.monitor._can_start_clicking(123_500, anchors(), self.now))

    def test_ocr_disagreement_resets_candidate(self) -> None:
        self.observe(123_000, "frame-1", 0)
        self.monitor.state.ocr_status = OcrStatus.ERROR
        self.observe(123_500, "frame-2", 200)

        self.assertEqual(self.monitor.state.phase, MonitorPhase.WAITING)
        self.assertEqual(self.monitor.state.candidate_hits, 0)

    def test_incompatible_growth_restarts_without_confirmation(self) -> None:
        self.observe(123_000, "frame-1", 0)
        self.observe(190_000, "frame-2", 200)

        self.assertEqual(self.monitor.state.phase, MonitorPhase.CANDIDATE)
        self.assertEqual(self.monitor.state.candidate_hits, 1)
        self.assertEqual(self.monitor.state.candidate_value, 190_000)

    def test_bad_anchors_block_confirmation_and_taps(self) -> None:
        for frame_anchors in (anchors(False, True), anchors(True, False)):
            with self.subTest(frame_anchors=frame_anchors):
                self.monitor.state.phase = MonitorPhase.WAITING
                self.observe(123_000, "frame-1", 0)
                self.observe(123_500, "frame-2", 200, frame_anchors)
                self.assertEqual(self.monitor.state.phase, MonitorPhase.WAITING)
                self.assertEqual(self.monitor.state.candidate_hits, 0)
                self.assertFalse(
                    self.monitor._can_start_clicking(123_500, frame_anchors, self.now)
                )

    def test_test_mode_virtual_tap_never_calls_adb(self) -> None:
        self.observe(123_000, "frame-1", 0)
        self.observe(123_500, "frame-2", 200)
        self.assertTrue(self.monitor._can_start_clicking(123_500, anchors(), self.now))
        self.monitor.state.phase = MonitorPhase.ACTIVE_CLICKING
        self.monitor.state.next_click_at = self.now

        clicked, would_tap, _ = self.monitor._handle_active_clicking(
            self.now,
            Image.new("RGB", (16, 16), "white"),
            recognition(),
            anchors(),
            [],
        )

        self.assertTrue(would_tap)
        self.assertFalse(clicked)
        self.assertEqual(self.monitor.adb.tap_calls, [])

    def test_two_poll_frames_start_active_clicking_without_adb(self) -> None:
        values = iter((123_000, 123_500))
        screen = Image.new("RGB", (1120, 1100), "white")
        prefilter = PrefilterResult(
            status="synthetic",
            confidence=1.0,
            digit_count=6,
            first_digit=1,
            reason="isolated test",
            timings_ms={},
            possible_reset=False,
            raw_prefix="123",
        )

        def capture_context(now: datetime):
            value = next(values)
            self.monitor._latest_capture_completed_at = now
            return screen, recognition(value), anchors(), prefilter, 0.0, 0.0, 0.0, True

        self.monitor._capture_context = capture_context
        self.monitor._append_observation = lambda *_args, **_kwargs: None
        self.monitor._update_reset_episode_lock = lambda *_args, **_kwargs: None
        self.monitor._update_reset_detection = lambda value, *_args, **_kwargs: (
            setattr(self.monitor.state, "last_confirmed_prize", value),
            setattr(self.monitor.state, "last_trusted_at", self.now),
        )
        self.monitor._save_persisted_state = lambda: None
        self.monitor._history_stats = lambda: ("insufficient", "insufficient", "insufficient")
        self.monitor._history_rows = lambda: []
        self.monitor._history_since_reset_label = lambda _now: "unknown"
        self.monitor._format_since_reset_label = lambda _now: "unknown"
        self.monitor._last_production_ocr = None
        self.monitor.reset_history = []

        first = self.monitor.poll_once()
        self.now += timedelta(milliseconds=200)
        second = self.monitor.poll_once()

        self.assertEqual(first.phase, MonitorPhase.CANDIDATE)
        self.assertEqual(second.phase, MonitorPhase.ACTIVE_CLICKING)
        self.assertTrue(second.would_tap)
        self.assertFalse(second.clicked)
        self.assertEqual(self.monitor.adb.tap_calls, [])

    def test_scheduler_has_500ms_spacing_without_catch_up(self) -> None:
        self.monitor.state.phase = MonitorPhase.ACTIVE_CLICKING
        self.monitor.state.next_click_at = self.now
        screen = Image.new("RGB", (16, 16), "white")

        def tick(offset_ms: int) -> tuple[bool, bool]:
            self.now = datetime(2026, 7, 16, 12, 0, 0) + timedelta(milliseconds=offset_ms)
            self.monitor._latest_capture_completed_at = self.now
            clicked, would_tap, _ = self.monitor._handle_active_clicking(
                self.now, screen, recognition(), anchors(), []
            )
            return clicked, would_tap

        self.assertEqual(tick(0), (False, True))
        self.assertEqual(tick(499), (False, False))
        self.assertEqual(tick(500), (False, True))
        self.assertEqual(tick(2_000), (False, True))
        self.assertEqual(tick(2_001), (False, False))
        self.assertEqual(self.monitor.state.burst_taps_done, 3)
        self.assertEqual(self.monitor.config.burst_size, 8)
        self.assertEqual(self.monitor.adb.tap_calls, [])

    def test_notification_immediately_stops_active_series(self) -> None:
        self.monitor.state.phase = MonitorPhase.ACTIVE_CLICKING
        self.monitor.state.next_click_at = self.now
        self.monitor.state.notification_veto = True

        clicked, would_tap, _ = self.monitor._handle_active_clicking(
            self.now,
            Image.new("RGB", (16, 16), "white"),
            recognition(),
            anchors(),
            [],
        )

        self.assertFalse(clicked)
        self.assertFalse(would_tap)
        self.assertEqual(self.monitor.state.phase, MonitorPhase.CHECKING_AFTER_BURST)
        self.assertEqual(self.monitor.adb.tap_calls, [])


if __name__ == "__main__":
    unittest.main()
