import unittest

from app.observation_activity import ObservationActivity
from app.monitor import MonitorPhase
from app.ui import poll_delay_ms


class ObservationActivityTests(unittest.TestCase):
    def setUp(self):
        self.activity = ObservationActivity()

    def observe(self, **changes):
        values = dict(screen_ok=True, notification=False, balance=None, reset_at=None)
        values.update(changes)
        return self.activity.observe(**values)

    def test_reward_notification_starts_fast_observation(self):
        self.assertTrue(self.observe(notification=True))
        self.assertTrue(self.observe())

    def test_confirmed_wish_cost_starts_fast_observation(self):
        self.assertFalse(self.observe(balance=12000))
        self.assertTrue(self.observe(balance=11900))

    def test_multiple_wishes_between_wallet_reads_are_detected(self):
        self.observe(balance=12000)
        self.assertTrue(self.observe(balance=11300))

    def test_other_balance_changes_do_not_trigger_acceleration(self):
        for balance in (12100, 12000, 11901):
            with self.subTest(balance=balance):
                self.activity = ObservationActivity()
                self.observe(balance=12000)
                self.assertFalse(self.observe(balance=balance))

    def test_unknown_wallet_does_not_invent_spending(self):
        self.assertFalse(self.observe(balance=None))
        self.assertFalse(self.observe(balance=11900))

    def test_wrong_screen_does_not_trigger(self):
        self.observe(balance=12000)
        self.assertFalse(self.observe(screen_ok=False, notification=True, balance=11900))
        self.assertFalse(self.observe(balance=11800))

    def test_reset_stops_fast_observation_and_ignores_old_notification(self):
        self.assertTrue(self.observe(notification=True))
        self.assertFalse(self.observe(reset_at='new reset', notification=True))
        self.assertFalse(self.observe(reset_at='new reset', notification=True))
        self.assertFalse(self.observe(reset_at='new reset'))
        self.assertTrue(self.observe(reset_at='new reset', notification=True))

    def test_existing_reset_at_start_is_not_click_activity(self):
        self.assertFalse(self.observe(reset_at='previous reset'))
        self.assertFalse(self.observe(reset_at='previous reset', balance=12000))
        self.assertTrue(self.observe(reset_at='previous reset', balance=11900))

    def test_pause_clears_activity_and_wallet_baseline(self):
        self.observe(balance=12000)
        self.assertTrue(self.observe(notification=True))
        self.assertFalse(self.observe(paused=True))
        self.assertFalse(self.observe(balance=11900))

    def test_fast_observation_only_changes_scheduler(self):
        self.assertEqual(poll_delay_ms(MonitorPhase.WAITING, 200, True), 1)
        self.assertEqual(poll_delay_ms(MonitorPhase.WAITING, 200, False), 200)

    def test_full_reset_confirmation_turns_acceleration_off_without_taps(self):
        from tests.test_reset_observation_gap import ResetObservationGapTests
        fixture = ResetObservationGapTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.monitor._observation_activity = self.activity
        self.observe(notification=True)
        first = fixture.poll(14500, 1)
        self.assertTrue(fixture.monitor.state.fast_observation_active)
        self.assertFalse(first.clicked or first.would_tap)
        second = fixture.poll(14700, .5)
        self.assertEqual(second.phase, MonitorPhase.RESET_COOLDOWN)
        self.assertFalse(fixture.monitor.state.fast_observation_active)
        self.assertEqual(fixture.monitor.adb.tap_calls, [])
