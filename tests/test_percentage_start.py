from dataclasses import replace
from datetime import timedelta
import unittest
from app.monitor import MonitorPhase
from app.persistence import PersistedState, ResetEvent, UserRangeConfig
from tests.test_in_range_confirmation import InRangeConfirmationTests, anchors


class PercentageStartTests(unittest.TestCase):
    def setUp(self):
        InRangeConfirmationTests.setUp(self)
        self.addCleanup(self.temp_dir.cleanup)
        self.monitor.user_range = replace(self.monitor.user_range, start_method='percent', start_percent=85)
        self.monitor.reset_history = [ResetEvent(self.now.isoformat(), peak_before_reset=100000)]

    def test_threshold_is_inclusive_and_has_no_upper_limit(self):
        self.assertEqual(self.monitor.percentage_start_threshold(), 85000)
        self.assertFalse(self.monitor.is_target_value(84999))
        self.assertTrue(self.monitor.is_target_value(85000))
        self.assertTrue(self.monitor.is_target_value(500000))
        self.assertEqual(self.monitor.target_range_for_mode(False), self.monitor.target_range_for_mode(True))

    def test_two_independent_readings_confirm_percentage_start(self):
        m = self.monitor
        m._update_candidate(85000, 'percent-a', self.now, anchors())
        self.assertEqual(m.state.phase, MonitorPhase.CANDIDATE)
        m._update_candidate(85500, 'percent-b', self.now+timedelta(milliseconds=500), anchors())
        self.assertEqual(m.state.phase, MonitorPhase.CONFIRMED)
        self.assertEqual(m.adb.tap_calls, [])

    def test_new_reset_updates_threshold(self):
        self.monitor.reset_history.append(ResetEvent((self.now+timedelta(seconds=1)).isoformat(), peak_before_reset=200000))
        self.assertEqual(self.monitor.percentage_start_threshold(), 170000)

    def test_missing_peak_does_not_reuse_older_event(self):
        self.monitor.reset_history.append(ResetEvent((self.now+timedelta(seconds=1)).isoformat()))
        self.assertFalse(self.monitor.is_target_value(85000))

    def test_no_history_blocks_start(self):
        self.monitor.reset_history = []
        self.assertFalse(self.monitor.is_target_value(85000))

    def test_percentage_rounds_up(self):
        self.monitor.reset_history[0].peak_before_reset = 100001
        self.assertEqual(self.monitor.percentage_start_threshold(), 85001)

    def test_cooldown_is_still_required(self):
        self.monitor.state.candidate_hits = 2
        self.monitor.state.cooldown_until = self.now+timedelta(seconds=120)
        self.assertFalse(self.monitor._can_start_clicking(85000, anchors(), self.now))
        self.assertTrue(self.monitor._can_start_clicking(85000, anchors(), self.now+timedelta(seconds=120)))

    def test_stale_reset_starts_new_observation_without_deleting_history(self):
        m = self.monitor
        old = self.now-timedelta(minutes=30)
        m.reset_history = [ResetEvent(old.isoformat(), peak_before_reset=100000)]
        PersistedState(last_reset_at=old, reset_time_known=True, last_trusted_at=self.now,
                       last_confirmed_prize=90000).save(m.config.state_path)
        m._load_persisted_state()
        self.assertEqual(m.state.phase, MonitorPhase.RESET_TIME_UNKNOWN)
        self.assertFalse(m.state.reset_time_known)
        self.assertIsNone(m.state.last_confirmed_prize)
        self.assertIsNone(m.percentage_start_threshold())
        self.assertEqual(len(m.reset_history), 1)
        m.reset_history.insert(0, ResetEvent((self.now+timedelta(seconds=1)).isoformat(), peak_before_reset=120000))
        self.assertEqual(m.percentage_start_threshold(), 102000)

    def test_recent_reset_keeps_existing_deadline(self):
        m = self.monitor
        old = self.now-timedelta(seconds=50)
        m.reset_history = [ResetEvent(old.isoformat(), peak_before_reset=100000)]
        until = old+timedelta(seconds=120)
        PersistedState(last_reset_at=old, reset_time_known=True, cooldown_until=until,
                       last_trusted_at=self.now).save(m.config.state_path)
        m._load_persisted_state()
        self.assertEqual(m.state.cooldown_until, until)
        self.assertEqual(m._cooldown_remaining(self.now), 70)
        self.assertEqual(m.percentage_start_threshold(), 85000)

    def test_setting_round_trip_and_invalid_percent(self):
        path = self.monitor.config.user_config_path
        self.monitor.user_range.save(path)
        loaded = UserRangeConfig.load(path, 1, 2)
        self.assertEqual((loaded.start_method, loaded.start_percent), ('percent', 85))
        self.assertFalse(self.monitor.update_test_range(100000, 200000, start_percent=101)[0])
        self.assertFalse(self.monitor.update_test_range(100000, 200000, start_percent=0)[0])
