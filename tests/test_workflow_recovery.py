from dataclasses import replace
from datetime import timedelta
from PIL import Image
from tests.test_in_range_confirmation import InRangeConfirmationTests, anchors, recognition
from app.monitor import MonitorPhase


class WorkflowTests(InRangeConfirmationTests):
    def test_rearm_discards_virtual_candidate(self):
        self.monitor.state.candidate_hits = 2
        self.monitor.state.phase = MonitorPhase.ACTIVE_CLICKING
        self.monitor.set_real_mode(True)
        self.assertEqual(self.monitor.state.candidate_hits, 0)
        self.assertEqual(self.monitor.state.phase, MonitorPhase.WAITING)

    def test_missing_read_then_new_confirmation(self):
        m = self.monitor
        m.state.phase = MonitorPhase.ACTIVE_CLICKING
        result = m._handle_active_clicking(self.now, Image.new('RGB',(1080,1080)), recognition(), None, anchors(), [])
        self.assertFalse(result[0] or result[1])
        self.assertEqual(m.state.phase, MonitorPhase.WAITING)
        self.observe(123000, 'new-a', 500)
        self.observe(123500, 'new-b', 1000)
        self.assertEqual(m.state.phase, MonitorPhase.CONFIRMED)

    def test_old_baseline_is_not_reset_evidence(self):
        m=self.monitor
        m.state.last_confirmed_prize=200000
        m.state.last_trusted_at=self.now-timedelta(days=30)
        m.state.cooldown_until=self.now+timedelta(seconds=70)
        deadline=m.state.cooldown_until
        m._discard_stale_observation(self.now)
        self.assertIsNone(m.state.last_confirmed_prize)
        self.assertIsNone(m.state.peak_since_reset)
        self.assertEqual(m.state.cooldown_until,deadline)
        self.assertFalse(m.state.reset_time_known)

    def test_real_limit_is_session_wide(self):
        m=self.monitor
        m.config=replace(m.config,session_real_tap_limit=2)
        m.adb.close_shell=lambda:None
        m.state.real_mode_armed=True
        m.state.phase=MonitorPhase.ACTIVE_CLICKING
        for i in range(2):
            self.now += timedelta(seconds=1)
            m._latest_capture_completed_at=self.now
            m._handle_active_clicking(self.now,Image.new('RGB',(1080,1080)),recognition(),123500,anchors(),[])
        self.assertEqual(len(m.adb.tap_calls),2)
        self.assertFalse(m.state.real_mode_armed)
        self.assertEqual(m.state.phase,MonitorPhase.PAUSED)
        self.assertFalse(m.set_real_mode(True)[0])
