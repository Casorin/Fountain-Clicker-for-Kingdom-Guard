import threading
import unittest
from unittest.mock import Mock

from PIL import Image
from app.gem_guard import GemGuard


class AsyncWalletTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.guard = GemGuard(None, clock=lambda: self.now)
        self.guard.read = Mock(return_value=40500)
        self.image = Image.new('RGB', (1080,1080))

    def finish(self):
        self.guard._refresh_thread.join(2)
        self.assertFalse(self.guard._refresh_thread.is_alive())

    def test_slow_read_does_not_block_click_worker(self):
        entered, release = threading.Event(), threading.Event()
        def read(_image):
            entered.set()
            release.wait(2)
            return 40500
        self.guard.read = read
        try:
            self.guard.refresh_async(self.image, frame_time=self.now)
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.guard._refresh_thread.is_alive())
            self.assertEqual(self.guard.permits_cached(40000), (False, 'unknown'))
            self.guard.refresh_async(self.image, frame_time=self.now)
        finally:
            release.set()
            self.finish()
        self.assertEqual(self.guard.permits_cached(40000), (True, 'ok'))

    def test_every_sent_tap_reduces_cached_budget(self):
        self.guard.refresh_async(self.image, frame_time=self.now)
        self.finish()
        for _ in range(5):
            self.assertTrue(self.guard.permits_cached(40000)[0])
            self.guard.reserve_sent_tap()
        self.assertEqual(self.guard.permits_cached(40000), (False, 'floor'))

    def test_slow_completed_read_is_not_declared_fresh(self):
        self.guard.refresh_async(self.image, frame_time=self.now)
        self.finish()
        self.now += 1
        self.assertEqual(self.guard.permits_cached(40000), (False, 'unknown'))

    def test_background_result_preserves_taps_sent_while_reading(self):
        entered, release = threading.Event(), threading.Event()
        def read(_image):
            entered.set()
            release.wait(2)
            return 40500
        self.guard.read = read
        try:
            self.guard.refresh_async(self.image, frame_time=self.now)
            self.assertTrue(entered.wait(1))
            self.guard.reserve_sent_tap()
            self.guard.reserve_sent_tap()
        finally:
            release.set()
            self.finish()
        self.assertEqual(self.guard.estimated, 40300)

    def test_unreadable_balance_fails_closed(self):
        self.guard.read.return_value = None
        self.guard.refresh_async(self.image, frame_time=self.now)
        self.finish()
        self.assertEqual(self.guard.permits_cached(40000), (False, 'unknown'))

    def test_read_error_fails_closed(self):
        self.guard.read.side_effect = RuntimeError('read failed')
        self.guard.refresh_async(self.image, frame_time=self.now)
        self.finish()
        self.assertEqual(self.guard.permits_cached(40000), (False, 'unknown'))
        self.assertEqual(self.guard.error, 'read failed')
