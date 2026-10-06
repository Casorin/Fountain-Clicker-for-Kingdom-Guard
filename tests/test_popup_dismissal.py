import unittest
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

from PIL import Image
from app.popup_dismissal import Popup, PopupDismissal
from app.monitor import MonitorPhase
from app.fast_ocr import PrefilterResult
from app.recognition import RecognitionResult
from tests import test_in_range_confirmation as confirmation


class PopupTests(unittest.TestCase):
    def frame(self, kind, body=True, close=True):
        detector = PopupDismissal()
        image = Image.new("RGB", (1080, 1080), "#193c57")
        x, y = (777, 315) if kind == "rating" else (716, 784)
        if close:
            image.paste(Image.fromarray(detector.templates[kind+"_close"]), (x, y))
        offsets = [(-375, -5), (-474, 174)] if kind == "rating" else [(-590, 117)]
        if body:
            for i, (dx, dy) in enumerate(offsets):
                image.paste(Image.fromarray(detector.templates[f"{kind}_{i}"]), (x+dx, y+dy))
        return image

    def test_both_known_dialogs(self):
        d = PopupDismissal()
        self.assertEqual(d.detect(self.frame("rating")), Popup("rating", (797, 336)))
        self.assertEqual(d.detect(self.frame("alliance")), Popup("alliance", (749, 815)))

    def test_cross_alone_never_sufficient(self):
        d = PopupDismissal()
        for kind in ("rating", "alliance"):
            self.assertIsNone(d.detect(self.frame(kind, body=False)))
            self.assertIsNone(d.detect(self.frame(kind, close=False)))

    def test_wrong_resolution_rejected(self):
        self.assertIsNone(PopupDismissal().detect(self.frame("rating").resize((720, 720))))

    def test_independent_confirmation_one_attempt_and_clear(self):
        d = PopupDismissal()
        p = Popup("rating", (797, 336))
        self.assertFalse(d.observe(p, 1))
        self.assertFalse(d.observe(p, 1))
        self.assertTrue(d.observe(p, 2))
        d.reserve_attempt()
        self.assertFalse(d.observe(p, 3))
        self.assertFalse(d.observe(None, 4))
        self.assertFalse(d.observe(None, 4))
        self.assertFalse(d.observe(None, 5))
        self.assertFalse(d.observe(p, 6))
        for frame in (7, 8, 9):
            d.observe(None, frame)
        self.assertFalse(d.observe(p, 10))
        self.assertTrue(d.observe(p, 11))


class PopupMonitorTests(unittest.TestCase):
    setUp = confirmation.InRangeConfirmationTests.setUp
    tearDown = confirmation.InRangeConfirmationTests.tearDown

    def prepare(self):
        m = self.monitor
        image = PopupTests().frame("rating")
        popup = m._popup_dismissal.detect(image)
        m.config = replace(m.config, screenshot_path=Path(self.temp_dir.name)/"screen.png")
        self.calls = []
        m._stream = SimpleNamespace(frame=lambda: SimpleNamespace(image=image),
                                    tap=lambda *point: self.calls.append(point))
        def capture(now):
            m._stream_sequence += 1
            m._current_popup = popup
            return (image, RecognitionResult("", "", None, "popup", 0, "popup", False),
                    confirmation.anchors(False, False), PrefilterResult("NOT_RUN", 0, None, None, "popup", {}, False, ""),
                    0, 0, None, False)
        m._capture_context = capture
        m._append_observation = lambda *args: None
        m._save_persisted_state = lambda: None
        m._history_stats = lambda: ("unknown",)*3
        m._history_rows = lambda: []
        m._history_since_reset_label = lambda now: "unknown"
        m._format_since_reset_label = lambda now: "unknown"
        m._last_production_ocr = None
        m.reset_history = []

    def test_test_mode_closes_only_cross_once_and_stops_wishes(self):
        self.prepare()
        self.monitor.state.phase = MonitorPhase.ACTIVE_CLICKING
        self.monitor.state.continuous_session_active = True
        for _ in range(4):
            snapshot = self.monitor.poll_once()
            self.assertFalse(snapshot.clicked)
            self.assertFalse(snapshot.would_tap)
        self.assertEqual(self.calls, [(797, 336)])
        self.assertEqual(self.monitor.state.real_taps, 0)
        self.assertFalse(self.monitor.state.continuous_session_active)

    def test_pause_and_emergency_stop_forbid_dismissal(self):
        self.prepare()
        for phase in (MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP):
            self.monitor.state.phase = phase
            for _ in range(3):
                self.monitor.poll_once()
        self.assertEqual(self.calls, [])

    def test_cancel_event_forbids_dismissal(self):
        self.prepare()
        self.monitor._tap_cancel.set()
        for _ in range(3):
            self.monitor.poll_once()
        self.assertEqual(self.calls, [])
