import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from app.ui import AppWindow


class StartupReadinessTests(unittest.TestCase):
    def test_start_retries_inactive_windows_when_others_are_running(self):
        app = SimpleNamespace(_switching_window=False, _window_picker_active=False,
                              _selection_error=None, running=True, _group=Mock())
        AppWindow.start(app)
        app._group.start.assert_called_once()

    def test_start_is_queued_until_preparation_finishes(self):
        app = SimpleNamespace(_switching_window=False, _window_picker_active=False,
                              _selection_error=None, running=False, _cleanup_thread=None,
                              ocr_warmup_complete=False, _warmup_start_requested=False,
                              status_var=Mock(), _group=Mock())
        AppWindow.start(app)
        self.assertTrue(app._warmup_start_requested)
        app._group.start.assert_not_called()
        self.assertIn('автоматически', app.status_var.set.call_args.args[0])

    def test_completed_preparation_runs_queued_start(self):
        app = SimpleNamespace(_warmup_thread=None, ocr_warmup_error=None,
                              ocr_warmup_complete=False, ocr_warmup_report={},
                              status_var=Mock(), _append_log=Mock(), _write_runtime_status=Mock(),
                              _warmup_start_requested=True, start=Mock(), close_callback=None)
        AppWindow._poll_ocr_warmup(app)
        self.assertTrue(app.ocr_warmup_complete)
        app.start.assert_called_once()

    def test_preparation_error_never_starts_monitor(self):
        app = SimpleNamespace(_warmup_thread=None, ocr_warmup_error='test failure',
                              ocr_warmup_complete=False, status_var=Mock(),
                              _write_runtime_status=Mock(), start=Mock())
        AppWindow._poll_ocr_warmup(app)
        app.start.assert_not_called()
        self.assertFalse(app.ocr_warmup_complete)
