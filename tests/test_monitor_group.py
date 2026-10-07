import threading
import time
import unittest
from types import SimpleNamespace

from app.memu_windows import MemuWindow
from app.monitor import MonitorState, MonitorPhase
from app.monitor_group import MonitorGroup
from app.persistence import UserRangeConfig


class FakeMonitor:
    def __init__(self):
        self.config = SimpleNamespace(stream_transport_enabled=False, poll_interval_ms=10)
        self.state = MonitorState(phase=MonitorPhase.WAITING)
        self._tap_cancel = threading.Event()
        self.user_range = UserRangeConfig(60000,500000)
        self.closed = False
        self.failure = False
        self.reset_calls = 0
        self.history = ['saved reset']
    def reset_lock(self):
        self.reset_calls += 1
        self.state.last_value = None
        self.state.last_reset_at = None
    def _now(self):
        return time.time()
    def _save_persisted_state(self):
        pass
    def set_real_mode(self, enabled):
        if enabled:
            raise AssertionError('No real mode in group tests')
        self.state.real_mode_armed = False
        self.state.test_mode = True
        self._tap_cancel.set()
        return True, 'test'
    def resume(self):
        self._tap_cancel.clear()
        self.state.phase = MonitorPhase.WAITING
    def pause(self):
        self._tap_cancel.set()
        self.state.phase = MonitorPhase.PAUSED
    def poll_once(self):
        if self.failure:
            raise RuntimeError('device offline')
        time.sleep(.003)
        if not self._tap_cancel.is_set():
            self.state.virtual_taps += 1
            self.state.last_value = 123000
        return SimpleNamespace(value=123000)
    def close(self):
        self._tap_cancel.set()
        self.closed = True
    def emergency_stop(self):
        self.pause()
        self.state.phase = MonitorPhase.EMERGENCY_STOP
    def _clear_candidate(self):
        self.state.candidate_hits = 0


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.monitors = [FakeMonitor(),FakeMonitor()]
        self.group = MonitorGroup([(MemuWindow(str(i),str(i),str(i)),m) for i,m in enumerate(self.monitors)])
    def tearDown(self):
        self.group.close()
    def wait_for(self, condition):
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.005)
        self.fail('Worker condition timed out')
    def test_two_workers_run_pause_and_close_independently(self):
        self.group.start()
        self.wait_for(lambda: all(m.state.virtual_taps >= 3 for m in self.monitors))
        self.group.pause()
        time.sleep(.03)
        counts = [m.state.virtual_taps for m in self.monitors]
        time.sleep(.06)
        self.assertEqual(counts,[m.state.virtual_taps for m in self.monitors])
        self.assertFalse(self.group.any_active)
        self.assertFalse(self.group.any_real)
        self.group.close()
        self.assertTrue(all(m.closed for m in self.monitors))
        self.assertTrue(all(not s.thread.is_alive() for s in self.group.sessions.values()))

    def test_reset_cycle_reaches_all_paused_workers_and_keeps_history(self):
        self.group.start()
        self.wait_for(lambda:all(m.state.virtual_taps>=2 for m in self.monitors))
        self.group.pause()
        time.sleep(.03)
        self.group.reset_cycle()
        self.wait_for(lambda:all(m.reset_calls==1 for m in self.monitors))
        for monitor in self.monitors:
            self.assertIsNone(monitor.state.last_value)
            self.assertIsNone(monitor.state.last_reset_at)
            self.assertFalse(monitor.state.reset_time_known)
            self.assertTrue(monitor.state.manual_reset_block_real_taps)
            self.assertFalse(monitor.state.real_mode_armed)
            self.assertEqual(monitor.history,['saved reset'])
            self.assertEqual(monitor.state.phase,MonitorPhase.RESET_TIME_UNKNOWN)

    def test_reset_cycle_before_start_applies_to_all_windows(self):
        self.group.reset_cycle()
        self.assertTrue(all(m.reset_calls==1 for m in self.monitors))
        self.assertFalse(self.group.any_real)

    def test_four_paused_workers_resume_even_if_pause_mode_was_consumed(self):
        self.group.close()
        self.monitors=[FakeMonitor() for _ in range(4)]
        self.group=MonitorGroup([(MemuWindow(str(i),str(i),str(i)),m) for i,m in enumerate(self.monitors)])
        self.group.start()
        self.wait_for(lambda:all(m.state.virtual_taps>=2 for m in self.monitors))
        self.group.pause()
        time.sleep(.05)
        for session in self.group.sessions.values():
            session.applied_mode_version=session.mode_version
            session.monitor.pause()
        counts=[m.state.virtual_taps for m in self.monitors]
        self.group.start()
        self.wait_for(lambda:all(m.state.virtual_taps>count for m,count in zip(self.monitors,counts)))
        self.assertTrue(all(m.state.phase==MonitorPhase.WAITING for m in self.monitors))
        self.assertTrue(all(not m.state.real_mode_armed for m in self.monitors))
    def test_one_failure_does_not_stop_other(self):
        self.monitors[0].failure = True
        self.group.start()
        self.wait_for(lambda: self.monitors[1].state.virtual_taps >= 5)
        self.assertFalse(self.group.sessions['0'].active.is_set())
        self.assertTrue(self.group.sessions['1'].active.is_set())
        self.assertFalse(self.group.sessions['0'].requested_real)
    def test_common_settings_but_separate_state(self):
        settings = UserRangeConfig(80000,200000,False,40000)
        self.group.update_settings(settings)
        self.group.start()
        self.wait_for(lambda: all(s.applied_settings_version == 1 for s in self.group.sessions.values()))
        self.assertTrue(all(m.user_range == settings for m in self.monitors))
        self.monitors[0].state.last_reset_at = 'first only'
        self.assertIsNone(self.monitors[1].state.last_reset_at)
    def test_f9_stops_all_workers(self):
        self.group.start()
        self.wait_for(lambda: all(m.state.virtual_taps >= 2 for m in self.monitors))
        self.group.emergency_stop()
        self.group.close()
        self.assertFalse(self.group.any_active)
        self.assertFalse(self.group.any_real)
        self.assertTrue(all(m.closed for m in self.monitors))

    def test_pause_retains_requested_click_mode_but_cancels_inputs(self):
        for session in self.group.sessions.values():
            session.requested_real = True
            session.monitor.state.real_mode_armed = True
            session.active.set()
        self.group.pause()
        self.assertTrue(self.group.any_real)
        self.assertFalse(self.group.any_active)
        for session in self.group.sessions.values():
            self.assertTrue(session.requested_real)
            self.assertFalse(session.monitor.state.real_mode_armed)
            self.assertTrue(session.monitor._tap_cancel.is_set())
            self.assertEqual(session.monitor.state.phase, MonitorPhase.PAUSED)

    def test_resume_reapplies_retained_click_mode_without_real_inputs(self):
        from unittest.mock import Mock
        for session in self.group.sessions.values():
            session.monitor.set_real_mode = Mock(return_value=(True, 'test'))
            session.request_mode(True)
        self.group.start()
        self.wait_for(lambda: all(m.state.virtual_taps >= 2 for m in self.monitors))
        self.group.pause()
        time.sleep(.03)
        counts = [m.state.virtual_taps for m in self.monitors]
        self.group.start()
        self.wait_for(lambda: all(m.state.virtual_taps > n for m, n in zip(self.monitors, counts)))
        for session in self.group.sessions.values():
            self.assertTrue(session.requested_real)
            self.assertTrue(session.monitor.set_real_mode.call_args.args[0])

    def test_emergency_stop_discards_retained_click_mode(self):
        for session in self.group.sessions.values():
            session.requested_real = True
        self.group.pause()
        self.assertTrue(self.group.any_real)
        self.group.emergency_stop()
        self.assertFalse(self.group.any_real)
        self.assertFalse(self.group.any_active)
