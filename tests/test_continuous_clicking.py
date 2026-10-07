from collections import deque
from dataclasses import replace
from datetime import timedelta
import unittest
from PIL import Image
from tests import test_in_range_confirmation as confirmation
from tests.test_in_range_confirmation import anchors, recognition
from tests.test_confirmed_decrease_reset import controlled_reading, neutral_prefilter
from app.monitor import MonitorPhase, OcrStatus, PrizeMonitor


class ContinuousTests(unittest.TestCase):
    def setUp(self):
        confirmation.InRangeConfirmationTests.setUp(self)
        self.monitor.config = replace(self.monitor.config, continuous_clicking=True)
        self.monitor.adb.close_shell = lambda: None
        self.monitor.state.candidate_hits = 2
        self.monitor.state.phase = MonitorPhase.ACTIVE_CLICKING
        self.origin = self.now

    def tearDown(self):
        self.temp_dir.cleanup()

    def tick(self, seconds, value=123500, obscured=False, frame_anchors=None, stale=False):
        self.now = self.origin + timedelta(seconds=seconds)
        self.monitor._latest_capture_completed_at = self.now - timedelta(seconds=2 if stale else 0)
        self.monitor.state.notification_veto = obscured
        self.monitor.state.ocr_status = OcrStatus.OBSCURED if obscured else OcrStatus.VISIBLE
        return self.monitor._handle_active_clicking(
            self.now, Image.new('RGB',(1080,1080)), recognition(value or 0), value,
            frame_anchors or anchors(), [])

    def test_series_does_not_end_at_old_burst_or_upper_range(self):
        for i in range(30):
            self.assertTrue(self.tick(i*.3, 123500+i*4000)[1])
        self.assertEqual(self.monitor.state.phase, MonitorPhase.ACTIVE_CLICKING)
        self.assertEqual(self.monitor.state.virtual_taps, 30)
        self.assertEqual(self.monitor.adb.tap_calls, [])

    def test_two_independent_poll_frames_start_continuous_session(self):
        self.monitor.state.phase = MonitorPhase.WAITING
        self.monitor.state.candidate_hits = 0
        confirmation.InRangeConfirmationTests.test_two_poll_frames_start_active_clicking_without_adb(self)
        self.assertTrue(self.monitor.state.continuous_session_active)

    def test_visible_continuation_frames_keep_tracking_fresh_and_confirm_reset(self):
        self.test_two_independent_poll_frames_start_continuous_session()
        m=self.monitor
        m._update_reset_detection=PrizeMonitor._update_reset_detection.__get__(m)
        m._save_reset_diagnostics=lambda *a,**k: None
        m._append_reset_history=lambda *a,**k: m.reset_history.append(a)
        m._resolve_trusted_value=lambda value,now:(value,'isolated trusted reading')
        a=replace(anchors(False,True),continuation_screen_ok=True)
        def capture(value):
            def context(now):
                m._latest_capture_completed_at=now
                return Image.new('RGB',(1080,1080)),controlled_reading(value),a,neutral_prefilter(),0,0,0,True
            m._capture_context=context
        for i in range(1,7):
            self.now=self.origin+timedelta(seconds=i*10)
            capture(123500+i*500)
            snapshot=m.poll_once()
            self.assertEqual(snapshot.phase,MonitorPhase.ACTIVE_CLICKING)
            self.assertEqual(m.state.last_trusted_at,self.now)
            self.assertTrue(m.state.reset_time_known)
        total=m.state.virtual_taps
        for i,value in enumerate([10000,10500]):
            self.now=self.origin+timedelta(seconds=61+i)
            capture(value)
            snapshot=m.poll_once()
            self.assertFalse(snapshot.would_tap)
        self.assertEqual(m.state.phase,MonitorPhase.RESET_COOLDOWN)
        self.assertEqual(m.state.virtual_taps,total)
        self.assertEqual(len(m.reset_history),1)

    def test_short_notification_continues_but_long_loss_holds(self):
        self.assertTrue(self.tick(0)[1])
        self.assertTrue(self.tick(.3, None, obscured=True)[1])
        self.assertTrue(self.tick(1.9, None, obscured=True)[1])
        self.assertFalse(self.tick(2.01, None, obscured=True)[1])
        self.assertTrue(self.monitor.state.continuous_session_active)
        self.assertTrue(self.tick(3, 210000)[1])

    def test_downward_read_stops_and_cannot_restart_blindly(self):
        self.tick(0)
        self.assertFalse(self.tick(.3, 10000)[1])
        self.assertTrue(self.monitor.state.session_reset_suspected)
        self.assertFalse(self.tick(.6, None, obscured=True)[1])
        self.assertEqual(self.monitor.state.virtual_taps, 1)

    def test_stale_frame_cannot_refresh_visibility_budget(self):
        self.tick(0)
        old = self.monitor.state.session_last_visible_at
        self.assertFalse(self.tick(1.5, 130000, stale=True)[1])
        self.assertEqual(self.monitor.state.session_last_visible_at, old)
        self.assertFalse(self.tick(2.1, None, obscured=True)[1])

    def test_lost_button_or_screen_ends_session(self):
        for a in [anchors(False, True), anchors(True, False)]:
            self.monitor.state.phase = MonitorPhase.ACTIVE_CLICKING
            self.monitor.state.candidate_hits = 2
            self.tick(0)
            self.assertFalse(self.tick(.3, None, True, a)[1])
            self.assertFalse(self.monitor.state.continuous_session_active)

    def test_continuation_anchors_cannot_start_session(self):
        a = replace(anchors(False, True), continuation_screen_ok=True)
        self.assertFalse(self.tick(0, frame_anchors=a)[1])
        self.assertFalse(self.monitor.state.continuous_session_active)

    def test_one_missing_video_button_frame_pauses_without_resetting_series(self):
        self.monitor._stream = object()
        self.tick(0)
        last_visible = self.monitor.state.session_last_visible_at
        self.assertFalse(self.tick(.3, None, True, anchors(False, False))[1])
        self.assertTrue(self.monitor.state.continuous_session_active)
        self.assertEqual(self.monitor.state.session_last_visible_at, last_visible)
        self.assertEqual(self.monitor.state.phase, MonitorPhase.ACTIVE_CLICKING)
        self.assertTrue(self.tick(.5)[1])
        self.assertIsNone(self.monitor.state.anchor_recovery_started_at)
        self.monitor._stream = None

    def test_missing_video_button_for_half_second_still_ends_series(self):
        self.monitor._stream = object()
        self.tick(0)
        self.assertFalse(self.tick(.3, None, True, anchors(False, False))[1])
        self.assertFalse(self.tick(.81, None, True, anchors(False, False))[1])
        self.assertFalse(self.monitor.state.continuous_session_active)
        self.assertEqual(self.monitor.state.phase, MonitorPhase.WAITING)
        self.monitor._stream = None

    def test_anchor_recovery_does_not_extend_hidden_fund_budget(self):
        self.monitor._stream = object()
        self.tick(0)
        self.tick(1.8, None, True, anchors(False, False))
        self.assertFalse(self.tick(2.1, None, True)[1])
        self.assertEqual(self.monitor.state.session_last_visible_at, self.origin)
        self.monitor._stream = None

    def test_late_safe_frame_cannot_resume_old_series(self):
        self.monitor._stream = object()
        self.tick(0)
        self.tick(.3, None, True, anchors(False, False))
        self.assertFalse(self.tick(.9)[1])
        self.assertFalse(self.monitor.state.continuous_session_active)
        self.monitor._stream = None

    def test_continuation_anchors_can_bridge_covered_prize_label(self):
        self.tick(0)
        a = replace(anchors(False, True), continuation_screen_ok=True)
        self.assertTrue(self.tick(.3, None, True, a)[1])

    def test_no_catch_up_and_minimum_interval(self):
        self.tick(0)
        self.assertFalse(self.tick(.1)[1])
        self.assertTrue(self.tick(.2)[1])
        self.assertTrue(self.tick(5)[1])
        self.assertFalse(self.tick(5)[1])
        self.assertEqual(self.monitor.state.virtual_taps, 3)

    def test_pause_and_f9_stop_all_events(self):
        self.tick(0)
        self.monitor.pause()
        self.assertFalse(self.tick(.3)[1])
        self.monitor.emergency_stop()
        self.assertFalse(self.tick(.6)[1])
        self.assertFalse(self.monitor.state.real_mode_armed)

    def test_limit_disarms_and_pauses(self):
        self.monitor.config = replace(self.monitor.config, continuous_max_taps=3)
        for i in range(3): self.assertTrue(self.tick(i*.3)[1])
        self.assertFalse(self.tick(1)[1])
        self.assertEqual(self.monitor.state.phase, MonitorPhase.PAUSED)
        self.assertFalse(self.monitor.state.real_mode_armed)

    def test_confirmed_reset_ends_continuous_session(self):
        m = self.monitor
        self.tick(0)
        m.state.last_confirmed_prize = 123500
        m.state.last_trusted_at = self.origin
        m.state.peak_since_reset = 123500
        m.reset_history = []
        m.recent_observations = deque()
        m._save_reset_diagnostics = lambda *a, **k: None
        m._save_persisted_state = lambda: None
        m._append_reset_history = lambda *a, **k: m.reset_history.append(a)
        for i,v in enumerate([10000,10500]):
            at = self.origin+timedelta(seconds=.3+i*.3)
            m._update_reset_detection(v,OcrStatus.VISIBLE,at,str(i),self.origin,
                                      controlled_reading(v),anchors(),neutral_prefilter())
        self.assertEqual(m.state.phase, MonitorPhase.RESET_COOLDOWN)
        self.assertFalse(m.state.continuous_session_active)
        self.assertEqual(len(m.reset_history),1)
        self.assertFalse(self.tick(1,11000)[1])
