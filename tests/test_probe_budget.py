import unittest
from unittest.mock import Mock
from scripts.bounded_click_probe import InputBudget
from app.adb_client import AdbError


class ProbeBudgetTests(unittest.TestCase):
    def test_never_sends_more_than_limit(self):
        send = Mock()
        budget = InputBudget(100)
        bounded = budget.wrap(send)
        for _ in range(100):
            bounded(1,2)
        with self.assertRaises(AdbError):
            bounded(1,2)
        self.assertEqual(send.call_count,100)

    def test_uncertain_failed_send_also_consumes_budget(self):
        budget = InputBudget(1)
        bounded = budget.wrap(Mock(side_effect=RuntimeError('uncertain send')))
        with self.assertRaises(RuntimeError):
            bounded(1,2)
        with self.assertRaises(AdbError):
            bounded(1,2)
        self.assertEqual(budget.reserved,1)
        self.assertEqual(budget.sent,0)
