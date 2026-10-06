import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from app.monitor import MonitorState, MonitorPhase
from app.shared_fund import SharedFund
from app.stream_transport import FreshFrameUnavailable


class SharedFundTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.source = SimpleNamespace(active=threading.Event())
        self.source.active.set()
        self.fund = SharedFund(self.source)
        self.monitor = SimpleNamespace(state=MonitorState(reset_time_known=True),
            _latest_capture_completed_at=self.now, reset_history=['event'], _now=lambda:self.now,
            config=SimpleNamespace(continuous_clicking=True,continuous_visibility_grace_seconds=2))
        self.snapshot = SimpleNamespace(trusted_value=100000, event_screen_ok=True,
                                        button_visible=True, notification_veto=False)
        self.follower = SimpleNamespace(state=MonitorState(), reset_history=[],
            _clear_candidate=Mock(), _now=lambda: self.now,
            config=SimpleNamespace(safety_frame_max_age_seconds=.75))

    def publish(self):
        self.fund.publish(self.monitor, self.snapshot)
        self.follower._shared_reading = self.fund.read(self.now, .75)
        return self.follower._shared_reading

    def test_fresh_reading_and_cycle_are_shared(self):
        reading = self.publish()
        self.fund.apply_cycle(self.follower, reading, self.now)
        self.assertEqual(reading.value, 100000)
        self.assertTrue(self.follower.state.reset_time_known)
        self.assertEqual(self.follower.reset_history, ['event'])
        self.assertTrue(self.fund.permits_current(self.follower))

    def test_stale_source_blocks_all_followers(self):
        self.publish()
        with self.assertRaises(FreshFrameUnavailable):
            self.fund.read(self.now+timedelta(seconds=1), .75)

    def test_paused_source_blocks_immediately(self):
        self.publish()
        self.source.active.clear()
        self.assertFalse(self.fund.permits_current(self.follower))

    def test_source_menu_popup_or_missing_number_invalidates(self):
        for field, value in [('event_screen_ok', False),
                             ('notification_veto', True), ('trusted_value', None)]:
            with self.subTest(field=field):
                original = getattr(self.snapshot, field)
                self.publish()
                setattr(self.snapshot, field, value)
                self.fund.publish(self.monitor, self.snapshot)
                self.assertFalse(self.fund.permits_current(self.follower))
                setattr(self.snapshot, field, original)

    def test_source_button_animation_does_not_hide_readable_fund(self):
        self.snapshot.button_visible = False
        self.assertEqual(self.publish().value,100000)

    def test_notification_grace_only_continues_existing_series(self):
        self.monitor.state.phase = MonitorPhase.ACTIVE_CLICKING
        self.monitor.state.continuous_session_active = True
        self.monitor.state.session_last_visible_at = self.now-timedelta(seconds=1)
        self.monitor.state.session_last_value = 100000
        self.snapshot.trusted_value = None
        self.snapshot.notification_veto = True
        reading = self.publish()
        self.assertTrue(reading.notification_grace)
        self.assertFalse(self.fund.permits_current(self.follower))
        self.follower.state.continuous_session_active = True
        self.assertTrue(self.fund.permits_current(self.follower))
        self.now += timedelta(seconds=2)
        self.monitor._latest_capture_completed_at = self.now
        self.fund.publish(self.monitor,self.snapshot)
        self.assertFalse(self.fund.permits_current(self.follower))

    def test_grace_never_applies_after_suspected_reset(self):
        self.monitor.state.phase = MonitorPhase.ACTIVE_CLICKING
        self.monitor.state.continuous_session_active = True
        self.monitor.state.session_last_visible_at = self.now
        self.monitor.state.session_last_value = 100000
        self.monitor.state.session_reset_suspected = True
        self.snapshot.trusted_value = None
        self.snapshot.notification_veto = True
        self.fund.publish(self.monitor,self.snapshot)
        with self.assertRaises(FreshFrameUnavailable):
            self.fund.read(self.now,.75)

    def test_source_pause_invalidates_previous_reading(self):
        self.publish()
        self.monitor.state.phase = MonitorPhase.PAUSED
        self.fund.publish(self.monitor,self.snapshot)
        self.assertFalse(self.fund.permits_current(self.follower))

    def test_drop_between_frame_and_tap_blocks_tap(self):
        self.publish()
        self.snapshot.trusted_value = 10000
        self.fund.publish(self.monitor, self.snapshot)
        self.assertFalse(self.fund.permits_current(self.follower))

    def test_reset_candidate_invalidates_without_waiting_for_confirmation(self):
        self.publish()
        self.monitor.state.reset_candidate_hits = 1
        self.fund.publish(self.monitor, self.snapshot)
        self.assertFalse(self.fund.permits_current(self.follower))

    def test_shared_reset_clears_series_and_sets_cooldown(self):
        self.monitor.state.last_reset_at = self.now
        self.monitor.state.cooldown_until = self.now+timedelta(seconds=120)
        self.follower.state.continuous_session_active = True
        self.fund.apply_cycle(self.follower, self.publish(), self.now)
        self.assertEqual(self.follower.state.phase, MonitorPhase.RESET_COOLDOWN)
        self.assertFalse(self.follower.state.continuous_session_active)
        self.assertFalse(self.fund.permits_current(self.follower))

    def test_history_is_not_a_mutable_shared_list(self):
        reading = self.publish()
        self.monitor.reset_history.append('later')
        self.assertEqual(reading.history, ('event',))

    def test_invalidation_blocks_before_next_poll(self):
        self.publish()
        self.fund.invalidate()
        self.assertFalse(self.fund.permits_current(self.follower))


class SharedFundCaptureTests(unittest.TestCase):
    def setUp(self):
        from tests.test_in_range_confirmation import InRangeConfirmationTests
        InRangeConfirmationTests.setUp(self)
        from collections import deque
        self.monitor._screen_geometry = None
        self.monitor.recent_prize_crops = deque(maxlen=4)
        self.monitor.gem_guard = Mock()
        self.monitor._ocr_pipeline = Mock()
        self.monitor._ocr_pipeline.process.side_effect = AssertionError('Follower must not OCR prize')
        self.source = SimpleNamespace(active=threading.Event())
        self.source.active.set()
        self.fund = SharedFund(self.source)
        source_monitor = SimpleNamespace(state=MonitorState(reset_time_known=True),
                                         reset_history=[], _latest_capture_completed_at=self.now,
                                         _now=lambda:self.now,config=self.monitor.config)
        snapshot = SimpleNamespace(trusted_value=123000, event_screen_ok=True,
                                   button_visible=True, notification_veto=False)
        self.fund.publish(source_monitor, snapshot)
        self.monitor._shared_fund = self.fund

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_follower_captures_local_screen_without_prize_ocr(self):
        from unittest.mock import patch
        from PIL import Image
        from tests.test_in_range_confirmation import anchors
        with patch('app.monitor.save_screen', return_value=Image.new('RGB', (1080,1080))), \
                patch('app.monitor.analyze_anchors', return_value=anchors()):
            result = self.monitor._capture_context(self.now)
        self.assertEqual(result[1].method, 'shared_fund')
        self.assertEqual(result[1].value, 123000)
        self.assertFalse(result[-1])
        self.monitor._ocr_pipeline.process.assert_not_called()
        self.monitor.gem_guard.refresh.assert_called_once()

    def test_missing_local_button_still_blocks_tap(self):
        from tests.test_in_range_confirmation import anchors, recognition
        from PIL import Image
        self.monitor._shared_reading = self.fund.read(self.now, .75)
        self.monitor.state.phase = MonitorPhase.ACTIVE_CLICKING
        self.monitor.state.candidate_hits = 2
        result = self.monitor._handle_active_clicking(
            self.now, Image.new('RGB',(1080,1080)), recognition(),123000,anchors(True,False),[])
        self.assertEqual(result[:2], (False, False))
        self.assertEqual(self.monitor.adb.tap_calls, [])

    def test_grace_cannot_start_follower_series(self):
        from dataclasses import replace
        from unittest.mock import patch
        from PIL import Image
        from tests.test_in_range_confirmation import anchors
        with self.fund.lock:
            self.fund.reading = replace(self.fund.reading,notification_grace=True)
        with patch('app.monitor.save_screen',return_value=Image.new('RGB',(1080,1080))), \
                patch('app.monitor.analyze_anchors',return_value=anchors()):
            with self.assertRaises(FreshFrameUnavailable):
                self.monitor._capture_context(self.now)
        self.assertEqual(self.monitor.adb.tap_calls, [])
