import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.ui import AppWindow
from app.user_guidance import action_block_reason, observation_help
from app.monitor import MonitorPhase, OcrStatus


class UserGuidanceTests(unittest.TestCase):
    def test_start_without_selection_explains_next_step(self):
        app = SimpleNamespace(_selection_error='not selected', status_var=Mock())
        with patch('app.ui.messagebox.showinfo') as notice:
            AppWindow.start(app)
        self.assertIn('Выбрать окно эмулятора', notice.call_args.args[1])

    def test_click_mode_without_selection_is_rejected_with_help(self):
        app = SimpleNamespace(_selection_error='not selected', status_var=Mock(), mode_var=Mock())
        app.mode_var.get.return_value = True
        with patch('app.ui.messagebox.showinfo') as notice:
            AppWindow._sync_mode(app)
        app.mode_var.set.assert_called_once_with(False)
        self.assertIn('Выбрать окно эмулятора', notice.call_args.args[1])

    def test_reset_without_selection_explains_instead_of_resetting(self):
        app = SimpleNamespace(_selection_error='not selected', status_var=Mock())
        with patch('app.ui.messagebox.showinfo') as notice, patch('app.ui.messagebox.askyesno') as confirm:
            AppWindow.reset_lock(app)
        notice.assert_called_once()
        confirm.assert_not_called()

    def test_busy_states_have_distinct_next_steps(self):
        for field, phrase in [('_switching_window', 'Подключаем'),
                              ('_window_picker_active', 'завершите выбор'),
                              ('_window_close_started', 'закрывается')]:
            self.assertIn(phrase, action_block_reason(SimpleNamespace(**{field: True})))

    def test_account_owned_by_another_clicker_has_specific_help(self):
        self.assertIn('другом окне кликера', action_block_reason(SimpleNamespace(_selection_error='уже используется')))

    def make_observing_app(self):
        snapshot = SimpleNamespace(event_screen_ok=True, button_visible=True, phase=MonitorPhase.WAITING,
                                   ocr_status=OcrStatus.VISIBLE, cooldown_remaining=63)
        monitor = SimpleNamespace(state=SimpleNamespace(start_requires_new_reset=False),
                                  user_range=SimpleNamespace(minimum_gems=None),
                                  target_range_label=lambda: '35 000–500 000')
        app = SimpleNamespace(running=True, mode_var=Mock(), monitor=monitor, _poll_result=snapshot)
        app.mode_var.get.return_value = True
        return app, snapshot

    def test_observation_explains_screen_cooldown_rule_and_without_clicks(self):
        app, snapshot = self.make_observing_app()
        self.assertIn('35 000', observation_help(app))
        snapshot.button_visible = False
        self.assertIn('Откройте фонтан', observation_help(app))
        snapshot.button_visible = True
        snapshot.phase = MonitorPhase.RESET_COOLDOWN
        self.assertIn('63 сек', observation_help(app))
        snapshot.phase = MonitorPhase.WAITING
        app.mode_var.get.return_value = False
        self.assertIn('Без кликов', observation_help(app))

    def test_reserve_and_obscured_numbers_have_help(self):
        app, snapshot = self.make_observing_app()
        app.monitor.user_range.minimum_gems = 40000
        app.monitor.gem_guard = SimpleNamespace(balance=None)
        self.assertIn('Проверяем запас', observation_help(app))
        app.monitor.gem_guard.balance = 40000
        self.assertIn('сохранить', observation_help(app))
        snapshot.ocr_status = OcrStatus.OBSCURED
        self.assertIn('уведомления', observation_help(app))
