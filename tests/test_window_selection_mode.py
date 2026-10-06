import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.ui import AppWindow


class WindowSelectionModeTests(unittest.TestCase):
    def test_opening_picker_does_not_pause_or_clear_pending_start(self):
        app = SimpleNamespace(
            _switching_window=False, _window_picker_active=False,
            _warmup_start_requested=True, pause=Mock(), root=Mock(),
            _base_config=SimpleNamespace(adb_path='adb.exe'), _group=None,
            config=SimpleNamespace(adb_serial='device-1'), _select_windows=Mock())
        with patch('app.window_picker.WindowPicker') as picker_class:
            AppWindow.choose_window(app)
            picker = picker_class.return_value
            dismissed = picker.bind.call_args.args[1]
            dismissed(SimpleNamespace(widget=picker))
        app.pause.assert_not_called()
        self.assertTrue(app._warmup_start_requested)
        self.assertFalse(app._window_picker_active)

    def test_confirming_same_windows_in_different_order_is_noop(self):
        windows = [SimpleNamespace(uuid='a', serial='one'),
                   SimpleNamespace(uuid='b', serial='two')]
        app = SimpleNamespace(_selected_windows=windows, pause=Mock(),
                              _switching_window=False, _warmup_start_requested=True)
        AppWindow._select_windows(app, list(reversed(windows)))
        app.pause.assert_not_called()
        self.assertFalse(app._switching_window)
        self.assertTrue(app._warmup_start_requested)

    def test_changed_selection_still_pauses_before_reconnection(self):
        app = SimpleNamespace(
            _selected_windows=[SimpleNamespace(uuid='a', serial='one')],
            pause=Mock(), status_var=Mock(), _poll_thread=Mock(), root=Mock())
        AppWindow._select_windows(app, [SimpleNamespace(uuid='b', serial='two')])
        app.pause.assert_called_once()
        self.assertTrue(app._switching_window)
        self.assertFalse(app._warmup_start_requested)


if __name__ == '__main__':
    unittest.main()
