import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.ui import AppWindow


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class RuleSwitchTests(unittest.TestCase):
    def make_app(self, mode=True, method='percent'):
        monitor = Mock()
        monitor.user_range = SimpleNamespace(start_method='range')
        monitor.update_test_range.return_value = (True, 'saved')
        return SimpleNamespace(
            mode_var=Variable(mode), start_method_var=Variable(method), monitor=monitor,
            test_range_min_var=Variable('35000'), test_range_max_var=Variable('500000'),
            gem_floor_var=Variable('40000'), gem_limit_enabled_var=Variable(False),
            start_percent_var=Variable('80'), no_upper_var=Variable(False),
            range_var=Variable(''), active_range_var=Variable(''), _group=Mock(),
            _append_log=Mock(), design=Mock())

    def test_confirmation_applies_and_saves_new_rule(self):
        app = self.make_app()
        app.apply_range = lambda: AppWindow.apply_range(app)
        with patch('app.ui.messagebox.askyesno', return_value=True) as confirm:
            AppWindow.on_start_method_changed(app)
        confirm.assert_called_once()
        self.assertEqual(app.monitor.update_test_range.call_args.kwargs['start_method'], 'percent')
        app._group.update_settings.assert_called_once()
        app.design.mark_saved.assert_called_once()

    def test_cancel_restores_previous_rule_without_saving(self):
        app = self.make_app()
        app.apply_range = lambda: AppWindow.apply_range(app)
        with patch('app.ui.messagebox.askyesno', return_value=False):
            AppWindow.on_start_method_changed(app)
        self.assertEqual(app.start_method_var.get(), 'range')
        app.monitor.update_test_range.assert_not_called()

    def test_invalid_settings_restore_previous_rule(self):
        app = self.make_app()
        app.start_percent_var.set('wrong')
        app.apply_range = lambda: AppWindow.apply_range(app)
        with patch('app.ui.messagebox.showerror'):
            AppWindow.on_start_method_changed(app)
        self.assertEqual(app.start_method_var.get(), 'range')
        app.monitor.update_test_range.assert_not_called()

    def test_no_click_mode_keeps_draft_without_confirmation(self):
        app = self.make_app(mode=False)
        app.apply_range = Mock()
        AppWindow.on_start_method_changed(app)
        app.apply_range.assert_not_called()
        self.assertEqual(app.start_method_var.get(), 'percent')

    def test_unchanged_rule_and_recursive_callback_are_noops(self):
        app = self.make_app(method='range')
        app.apply_range = Mock()
        AppWindow.on_start_method_changed(app)
        app._confirming_start_method = True
        app.start_method_var.set('percent')
        AppWindow.on_start_method_changed(app)
        app.apply_range.assert_not_called()


if __name__ == '__main__':
    unittest.main()
