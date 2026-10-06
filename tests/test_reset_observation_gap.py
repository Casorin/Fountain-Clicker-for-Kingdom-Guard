from datetime import timedelta
import unittest
from PIL import Image
from app.monitor import MonitorPhase
from tests.test_in_range_confirmation import InRangeConfirmationTests, anchors
from tests.test_confirmed_decrease_reset import controlled_reading, neutral_prefilter


class ResetObservationGapTests(unittest.TestCase):
    def setUp(self):
        InRangeConfirmationTests.setUp(self)
        self.addCleanup(self.temp_dir.cleanup)
        m = self.monitor
        m.reset_history = []
        m._last_production_ocr = None
        m._append_observation = lambda *args: None
        m._save_reset_diagnostics = lambda *args, **kwargs: None
        m._save_persisted_state = lambda: None
        m._history_stats = lambda: ('unknown', 'unknown', 'unknown')
        m._history_rows = lambda: []
        m._history_since_reset_label = lambda now: 'unknown'
        m._format_since_reset_label = lambda now: 'unknown'
        m.state.last_confirmed_prize = 120100
        m.state.peak_since_reset = 120100
        m.state.last_trusted_at = self.now
        m.state.reset_episode_token = 1
        m._last_observation_at = self.now
        # Keep this isolated exercise virtual even if its threshold is reached.
        m.tap_decisions_enabled = False

    def poll(self, value, seconds, screen_ok=True, button_ok=True):
        self.now += timedelta(seconds=seconds)
        m = self.monitor
        def capture(now):
            m._latest_capture_completed_at = now
            return (Image.new('RGB', (1080,1080)), controlled_reading(value),
                    anchors(screen_ok, button_ok), neutral_prefilter(), 0, 0, 0, True)
        m._capture_context = capture
        return m.poll_once()

    def test_live_drop_after_anchor_failures_is_confirmed_only_on_safe_frames(self):
        for _ in range(40):
            snapshot = self.poll(221400, 1, screen_ok=False)
            self.assertFalse(snapshot.would_tap or snapshot.clicked)
        self.assertEqual(self.monitor.state.last_confirmed_prize, 120100)
        self.poll(10950, 1, screen_ok=False)
        self.assertEqual(len(self.monitor.reset_history), 0)
        self.poll(14500, 1)
        self.assertEqual(len(self.monitor.reset_history), 0)
        self.poll(14700, .5)
        self.assertEqual(len(self.monitor.reset_history), 1)
        self.assertEqual(self.monitor.reset_history[0].peak_before_reset, 120100)
        self.assertEqual(self.monitor.state.phase, MonitorPhase.RESET_COOLDOWN)
        self.assertEqual(self.monitor.adb.tap_calls, [])

    def test_real_capture_gap_discards_baseline(self):
        self.poll(14500, 40)
        self.assertEqual(len(self.monitor.reset_history), 0)
        self.assertEqual(self.monitor.state.last_confirmed_prize, 14500)
        self.assertFalse(self.monitor.state.reset_time_known)

    def test_baseline_older_than_thirty_minutes_is_not_retained(self):
        self.monitor.state.last_trusted_at = self.now-timedelta(minutes=30)
        self.poll(14500, 1)
        self.assertEqual(len(self.monitor.reset_history), 0)
        self.assertFalse(self.monitor.state.reset_time_known)

    def test_unconfirmed_low_recovery_does_not_create_reset(self):
        for _ in range(40):
            self.poll(120100, 1, screen_ok=False)
        self.poll(14500, 1)
        self.poll(120100, .5)
        self.assertEqual(len(self.monitor.reset_history), 0)

    def test_missing_button_does_not_confirm_low_reset(self):
        self.poll(14500, 1, button_ok=False)
        self.poll(14700, 1, button_ok=False)
        self.assertEqual(len(self.monitor.reset_history), 0)
        self.assertEqual(self.monitor.adb.tap_calls, [])
