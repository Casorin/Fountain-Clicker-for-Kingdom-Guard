import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app.ui import AppWindow


class StartupReadinessTests(unittest.TestCase):
    def test_single_window_pause_does_not_change_click_mode(self):
        app = SimpleNamespace(running=True, _group=None, monitor=Mock(),
                              _refresh_static_panels=Mock(), status_var=Mock(),
                              phase_var=Mock(), _append_log=Mock(), _write_runtime_status=Mock())
        AppWindow.pause(app)
        self.assertFalse(app.running)
        app.monitor.pause.assert_called_once()
        app.monitor.set_real_mode.assert_not_called()

    def test_failed_preparation_can_be_retried_from_start(self):
        app = SimpleNamespace(_switching_window=False, _window_picker_active=False,
                              _selection_error=None, running=False, _cleanup_thread=None,
                              ocr_warmup_complete=False, ocr_warmup_error='old failure',
                              _warmup_thread=None, _start_ocr_warmup=Mock(),
                              status_var=Mock(), _group=Mock())
        AppWindow.start(app)
        app._start_ocr_warmup.assert_called_once()
        app._group.start.assert_not_called()
        self.assertTrue(app._warmup_start_requested)

    def run_warmup(self, runtime_dir, engines, deny_log=False):
        app = SimpleNamespace(config=SimpleNamespace(
            runtime_dir=runtime_dir, prize_crop_path=runtime_dir / 'crop.png',
            prize_crop=SimpleNamespace(width=40, height=20)),
            monitor=SimpleNamespace(_ocr_pipeline=SimpleNamespace(engines=engines)),
            status_var=Mock(), root=Mock(), _poll_ocr_warmup=Mock(),
            ocr_warmup_error='previous failure', ocr_warmup_report={'stale': True})
        original_open = Path.open

        def open_path(path, *args, **kwargs):
            if deny_log and path.name == 'startup_warmup.log':
                raise PermissionError('diagnostic log unavailable')
            return original_open(path, *args, **kwargs)

        with patch.dict('sys.modules', {'rapidocr': SimpleNamespace(), 'paddleocr': SimpleNamespace()}), \
                patch.object(Path, 'open', open_path):
            AppWindow._start_ocr_warmup(app)
            app._warmup_thread.join(timeout=3)
        self.assertFalse(app._warmup_thread.is_alive())
        return app

    def test_new_window_runtime_directory_is_created_before_warmup(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = Path(directory) / 'windows' / 'new-window'
            engines = Mock()
            engines.warm_up.return_value = {'ready': True}
            app = self.run_warmup(runtime_dir, engines)
            self.assertTrue((runtime_dir / 'startup_warmup.log').exists())
            self.assertIsNone(app.ocr_warmup_error)
            self.assertTrue(app.ocr_warmup_report['ready'])
            self.assertNotIn('stale', app.ocr_warmup_report)
            engines.warm_up.assert_called_once()

    def test_unwritable_diagnostic_log_does_not_block_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            engines = Mock()
            engines.warm_up.return_value = {'ready': True}
            app = self.run_warmup(Path(directory), engines, deny_log=True)
            self.assertIsNone(app.ocr_warmup_error)
            self.assertTrue(app.ocr_warmup_report['ready'])

    def test_actual_ocr_failure_is_still_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            engines = Mock()
            engines.warm_up.side_effect = RuntimeError('engine failed')
            app = self.run_warmup(Path(directory), engines)
            self.assertIn('engine failed', app.ocr_warmup_error)
            self.assertFalse(app.ocr_warmup_complete)

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
