from datetime import timedelta
import unittest

from app.monitor import MonitorPhase
from tests.test_reset_observation_gap import ResetObservationGapTests


class ModeResetAgeTests(unittest.TestCase):
    def setUp(self):
        ResetObservationGapTests.setUp(self)

    def age(self, seconds):
        self.monitor.state.last_reset_at = self.now-timedelta(seconds=seconds)
        self.monitor.state.last_reset_confirmed_at = self.monitor.state.last_reset_at

    def test_switch_uses_recent_reset_without_extra_two_minutes(self):
        for seconds in (120, 420, 899, 900):
            with self.subTest(seconds=seconds):
                self.age(seconds)
                self.monitor.state.reset_time_known = False
                self.monitor.set_real_mode(True)
                self.assertTrue(self.monitor.state.reset_time_known)
                self.assertIsNone(self.monitor.state.cooldown_until)
                self.assertFalse(self.monitor.state.start_requires_new_reset)

    def test_under_two_minutes_waits_only_remaining_time(self):
        self.age(90)
        self.monitor.set_real_mode(True)
        self.assertEqual(self.monitor.state.phase, MonitorPhase.RESET_COOLDOWN)
        self.assertEqual((self.monitor.state.cooldown_until-self.now).total_seconds(), 30)

    def test_older_than_fifteen_minutes_requires_actual_new_reset(self):
        self.age(901)
        self.monitor.set_real_mode(True)
        self.assertTrue(self.monitor.state.start_requires_new_reset)
        self.now += timedelta(minutes=3)
        self.monitor._update_unknown_and_cooldown(self.now)
        self.assertFalse(self.monitor.state.reset_time_known)
        self.assertEqual(self.monitor.state.phase, MonitorPhase.RESET_TIME_UNKNOWN)

    def test_interruption_keeps_recent_timer_but_discards_old_ocr(self):
        self.age(420)
        self.monitor._discard_stale_observation(self.now)
        self.assertTrue(self.monitor.state.reset_time_known)
        self.assertIsNone(self.monitor.state.last_confirmed_prize)
        self.assertIsNone(self.monitor.state.cooldown_until)

    def test_manual_wait_is_not_bypassed_by_recent_history(self):
        self.age(420)
        self.monitor.state.manual_reset_block_real_taps = True
        self.monitor.state.reset_time_known = False
        self.monitor.set_real_mode(True)
        self.assertFalse(self.monitor.state.reset_time_known)

    def test_new_reset_clears_old_cycle_block(self):
        self.age(901)
        self.monitor.set_real_mode(True)
        ResetObservationGapTests.poll(self, 14500, 1)
        ResetObservationGapTests.poll(self, 14700, .5)
        self.assertFalse(self.monitor.state.start_requires_new_reset)
        self.assertTrue(self.monitor.state.reset_time_known)
        self.assertEqual(self.monitor.state.phase, MonitorPhase.RESET_COOLDOWN)

    def test_missing_reset_date_requires_a_new_confirmed_reset(self):
        self.monitor.state.last_reset_at = None
        self.monitor.set_real_mode(True)
        self.assertTrue(self.monitor.state.start_requires_new_reset)
        self.assertFalse(self.monitor.state.reset_time_known)


if __name__ == '__main__':
    unittest.main()
