import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from app.bug_report import build_report, form_url, read_display_sizes, ReportWindow
from app.config import AppConfig
from app.monitor import MonitorState


class ReportTests(unittest.TestCase):
    def test_report_includes_picker_errors_even_without_selected_window(self):
        monitor = SimpleNamespace(state=MonitorState(), config=AppConfig())
        app = SimpleNamespace(monitor=monitor, running=False,
                              _window_preview_diagnostics=[('LDPlayer', 'Нет подключения к эмулятору.')])
        report = build_report(app)
        self.assertIn('Последняя проверка снимков', report)
        self.assertIn('LDPlayer): Нет подключения к эмулятору.', report)

    def test_sizes_use_read_only_android_command_for_each_window(self):
        monitors=[]
        for i in range(4):
            adb=Mock(serial=f'private-{i}')
            adb._run.return_value.stdout=b'Physical size: 1080x1920\nOverride size: 720x1280\n'
            monitors.append(('MEmu',SimpleNamespace(adb=adb),str(i)))
        self.assertEqual(read_display_sizes(monitors),{str(i):(720,1280) for i in range(4)})
        for _provider,monitor,_identifier in monitors:
            monitor.adb._run.assert_called_once_with('-s',monitor.adb.serial,'shell','wm','size',timeout=2)
            monitor.adb.tap.assert_not_called()
            monitor.adb.tap_persistent.assert_not_called()

    def test_four_windows_have_distinct_sizes_and_no_false_zero_size(self):
        sessions={str(i):SimpleNamespace(window=SimpleNamespace(provider='MEmu',uuid=str(i)),
                       monitor=SimpleNamespace(state=MonitorState(),_stream=None)) for i in range(4)}
        app=SimpleNamespace(monitor=SimpleNamespace(state=MonitorState(),config=AppConfig()),
                            running=False,_group=SimpleNamespace(sessions=sessions))
        report=build_report(app,{str(i):(720+i,1280+i) for i in range(4)})
        for i in range(4):
            self.assertIn(f'{720+i} × {1280+i}',report)
        self.assertNotIn('0 × 0',report)
        self.assertIn('Видеокадр: ещё не получен',report)

    def test_private_log_text_is_not_exported(self):
        state = MonitorState()
        monitor = SimpleNamespace(state=state, config=AppConfig())
        app = SimpleNamespace(monitor=monitor, running=False, _group=None,
                              log=Mock())
        app.log.get.return_value = 'timeout C:\\Users\\secret-name token=TOPSECRET 127.0.0.1 40000'
        report = build_report(app)
        for private in ('secret-name', 'TOPSECRET', '127.0.0.1', '40000'):
            self.assertNotIn(private, report)
        self.assertIn('Время ожидания истекло: 1', report)

    def test_prefill_is_encoded_and_never_submits_response(self):
        text = 'Диагностика\nБез кликов & безопасно'
        url = form_url(text)
        self.assertTrue(urlparse(url).path.endswith('/viewform'))
        self.assertEqual(parse_qs(urlparse(url).query)['entry.1882575839'], [text])
        self.assertNotIn('formResponse', url)

    def test_external_form_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'form.json'
            path.write_text(json.dumps({'url':'https://evil.example/viewform', 'diagnostics_field':'entry.1'}))
            with self.assertRaises(ValueError):
                form_url('test', path)


class ReportWindowTests(unittest.TestCase):
    def setUp(self):
        import test_ui_design
        from app.ui_design import PALETTES
        self.fixture=test_ui_design.DesignTests()
        self.fixture.setUp()
        self.root=self.fixture.root
        app=self.fixture.app
        app.monitor=SimpleNamespace(state=MonitorState(),config=AppConfig())
        app._group=None
        with patch('app.bug_report.read_display_sizes',return_value={'primary':(1080,1920)}):
            self.window=ReportWindow(self.root,app,PALETTES['light'])
            self.root.after(160,self.root.quit)
            self.root.mainloop()

    def tearDown(self):
        self.window.destroy()
        self.fixture.tearDown()

    def test_copy_has_visible_confirmation_and_returns_to_original_label(self):
        try:
            previous=self.root.clipboard_get()
        except Exception:
            previous=''
        try:
            self.window.copy_button.invoke()
            self.assertEqual(self.window.copy_button.cget('text'),'✓  Скопировано')
            self.assertEqual(self.root.clipboard_get(),self.window.report)
            self.root.after(2100,self.root.quit)
            self.root.mainloop()
            self.assertIn('Скопировать отчёт',self.window.copy_button.cget('text'))
        finally:
            self.root.clipboard_clear()
            self.root.clipboard_append(previous)

    def test_report_ready_with_native_size_and_footer_inside_small_window(self):
        self.assertIn('Android-экран: 1080 × 1920',self.window.report)
        self.window.geometry('680x540+10000+10000')
        self.root.update()
        for button in (self.window.copy_button,self.window.open_button):
            self.assertTrue(button.winfo_viewable())
            self.assertLessEqual(button.winfo_rooty()-self.window.winfo_rooty()+button.winfo_height(),self.window.winfo_height())
