from __future__ import annotations

import unittest

from app.monitor import MonitorPhase
from app.ui import poll_delay_ms


class PollSchedulerTests(unittest.TestCase):
    def test_active_clicking_uses_immediate_next_poll(self) -> None:
        self.assertEqual(poll_delay_ms(MonitorPhase.ACTIVE_CLICKING, 200), 1)

    def test_non_active_phases_keep_normal_delay(self) -> None:
        for phase in (MonitorPhase.WAITING, MonitorPhase.CANDIDATE, MonitorPhase.CHECKING_AFTER_BURST):
            with self.subTest(phase=phase):
                self.assertEqual(poll_delay_ms(phase, 200), 200)


if __name__ == "__main__":
    unittest.main()
