import json
import msvcrt
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from app.data_storage import clear_app_data, maintain_data, other_programs_running, HISTORY_LIMIT
from app.persistence import ResetEvent, save_reset_history, load_reset_history
from app.ui import AppWindow


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.installation = Path(self.temp.name)
        self.root = self.installation/'runtime'
        self.root.mkdir()
        self.now = time.time()

    def tearDown(self):
        self.temp.cleanup()

    def file(self,name,content=b'data',age=0):
        path = self.root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)
        os.utime(path,(self.now-age,self.now-age))
        return path

    def maintain(self,**kwargs):
        return maintain_data(self.root,installation_root=self.installation,now=self.now,**kwargs)

    def test_old_technical_data_removed_but_settings_and_history_preserved(self):
        paths = [self.file(name,age=8*86400) for name in (
            'debug/old.png','windows/a/triggers/x/frame.png','groups/b/backups/history.json',
            'reset_diagnostics/old.json','old.log','hotkey_commands/old.json')]
        protected = [self.file(name,age=100*86400) for name in (
            'user_config.json','production_reset_history.json','window_selection.json','onboarding.json')]
        self.assertEqual(self.maintain(),6)
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertTrue(all(path.exists() for path in protected))

    def test_size_limit_removes_oldest_diagnostics_across_profiles(self):
        oldest = self.file('windows/a/debug/a.png',b'a'*10,age=200)
        newer = self.file('groups/b/reset_diagnostics/b.png',b'b'*10,age=100)
        self.maintain(diagnostics_limit=10)
        self.assertFalse(oldest.exists())
        self.assertTrue(newer.exists())

    def test_current_diagnostic_write_is_not_removed(self):
        recent = self.file('triggers/current.png',b'x'*20,age=5)
        self.maintain(diagnostics_limit=1)
        self.assertTrue(recent.exists())

    def test_log_trim_keeps_latest_complete_lines(self):
        path = self.file('monitor_events.jsonl',b'old\n'*100+b'latest\n')
        self.maintain(log_limit=20)
        self.assertLessEqual(path.stat().st_size,20)
        self.assertTrue(path.read_bytes().endswith(b'latest\n'))

    def test_current_hotkey_command_is_kept(self):
        path = self.file('hotkey_commands/current.json',age=10)
        self.maintain()
        self.assertTrue(path.exists())

    def test_two_windows_cannot_trim_logs_at_the_same_time(self):
        path = self.file('debug/old.png',age=8*86400)
        with (self.root/'.cleanup.lock').open('w+b') as guard:
            guard.write(b'0')
            guard.flush()
            guard.seek(0)
            msvcrt.locking(guard.fileno(),msvcrt.LK_NBLCK,1)
            try:
                self.assertEqual(self.maintain(),0)
                self.assertTrue(path.exists())
            finally:
                guard.seek(0)
                msvcrt.locking(guard.fileno(),msvcrt.LK_UNLCK,1)

    def test_full_reset_only_removes_dedicated_runtime_folder(self):
        self.file('windows/a/user_config.json')
        self.file('groups/b/production_reset_history.json')
        asset = self.installation/'assets.txt'
        asset.write_text('keep',encoding='ascii')
        clear_app_data(self.root,installation_root=self.installation)
        self.assertFalse(self.root.exists())
        self.assertEqual(asset.read_text(),'keep')

    def test_reset_rejects_any_other_target(self):
        path = self.file('user_config.json')
        for target in (self.installation,self.root/'windows',self.installation/'other'):
            with self.assertRaises(ValueError):
                clear_app_data(target,installation_root=self.installation)
        self.assertTrue(path.exists())

    def test_reset_rescans_files_left_in_temporarily_nonempty_folder(self):
        import ctypes
        from app import data_reset
        self.file('windows/test/user_config.json')
        folder = self.root/'windows'/'test'
        original = Path.rmdir
        inserted = False
        def rmdir(path):
            nonlocal inserted
            if path == folder and not inserted:
                inserted = True
                (folder/'startup_warmup.log').write_text('late write')
                raise ctypes.WinError(145)
            return original(path)
        with patch('app.data_reset.DATA_ROOT',self.root), \
             patch('app.data_reset.ResetGuard',return_value=Mock(__enter__=Mock(),__exit__=Mock(return_value=False))), \
             patch('app.single_instance.SingleInstanceManager.process_is_running',return_value=False), \
             patch('app.data_reset.other_programs_running',return_value=False), \
             patch('app.data_reset.clear_app_data',side_effect=lambda: clear_app_data(self.root,installation_root=self.installation)) as clear, \
             patch('app.data_reset.subprocess.Popen') as restart, \
             patch('app.data_reset.time.sleep'),patch.object(Path,'rmdir',rmdir):
            data_reset.reset_and_restart(123)
        self.assertEqual(clear.call_count,2)
        self.assertFalse(self.root.exists())
        restart.assert_called_once()

    def test_directory_junction_is_never_followed(self):
        outside = self.installation/'outside'
        outside.mkdir()
        protected = outside/'private.log'
        protected.write_bytes(b'private')
        link = self.root/'debug'
        result = subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],capture_output=True,
                                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0)
        try:
            self.maintain(diagnostics_limit=0)
            with self.assertRaises(ValueError):
                clear_app_data(self.root,installation_root=self.installation)
            self.assertEqual(protected.read_bytes(),b'private')
        finally:
            link.rmdir()

    def test_another_running_profile_blocks_reset(self):
        self.file('groups/other/instance_state.json',json.dumps({'pid':123}).encode())
        with patch('app.single_instance.SingleInstanceManager.process_is_running',return_value=True):
            self.assertTrue(other_programs_running(self.root,current_pid=456))
            self.assertFalse(other_programs_running(self.root,current_pid=123))

    def test_history_is_bounded_on_disk_and_when_loading_legacy_files(self):
        path = self.root/'production_reset_history.json'
        events = [ResetEvent(timestamp_reset=f'event-{i}') for i in range(HISTORY_LIMIT+3)]
        save_reset_history(path,events)
        self.assertEqual(len(json.loads(path.read_text())),HISTORY_LIMIT)
        path.write_text(json.dumps([{'timestamp_reset':event.timestamp_reset} for event in events]))
        loaded = load_reset_history(path)
        self.assertEqual(len(loaded),HISTORY_LIMIT)
        self.assertEqual(loaded[0].timestamp_reset,'event-0')
        self.assertEqual(len(json.loads(path.read_text())),HISTORY_LIMIT)


class ResetActionTests(unittest.TestCase):
    def app(self):
        from types import SimpleNamespace
        return SimpleNamespace(_switching_window=False,_window_picker_active=False,
            root=Mock(),status_var=Mock(),emergency_stop=Mock(),close_callback=Mock())

    def test_cancel_preserves_data_and_does_not_stop_work(self):
        app = self.app()
        with patch('app.data_storage.other_programs_running',return_value=False), \
             patch('app.ui.messagebox.askyesno',return_value=False), \
             patch('app.data_reset.launch_reset_helper') as helper:
            AppWindow.reset_all_data(app)
        app.emergency_stop.assert_not_called()
        helper.assert_not_called()
        app.close_callback.assert_not_called()

    def test_confirmed_reset_stops_clicks_before_helper_and_close(self):
        app = self.app()
        order = Mock()
        order.attach_mock(app.emergency_stop,'stop')
        order.attach_mock(app.close_callback,'close')
        with patch('app.data_storage.other_programs_running',return_value=False), \
             patch('app.ui.messagebox.askyesno',return_value=True), \
             patch('app.data_reset.launch_reset_helper') as helper:
            order.attach_mock(helper,'helper')
            AppWindow.reset_all_data(app)
        self.assertEqual([call[0] for call in order.mock_calls],['stop','helper','close'])
        self.assertTrue(app._resetting_data)
        self.assertFalse(app._warmup_start_requested)

    def test_other_windows_block_reset_with_explanation(self):
        app = self.app()
        with patch('app.data_storage.other_programs_running',return_value=True), \
             patch('app.ui.messagebox.showinfo') as notice, \
             patch('app.ui.messagebox.askyesno') as confirmation:
            AppWindow.reset_all_data(app)
        confirmation.assert_not_called()
        app.emergency_stop.assert_not_called()
        self.assertIn('остальные окна',notice.call_args.args[1])

    def test_failed_helper_keeps_gui_open_and_clicks_stopped(self):
        app = self.app()
        with patch('app.data_storage.other_programs_running',return_value=False), \
             patch('app.ui.messagebox.askyesno',return_value=True), \
             patch('app.data_reset.launch_reset_helper',side_effect=OSError), \
             patch('app.ui.messagebox.showinfo') as notice:
            AppWindow.reset_all_data(app)
        app.emergency_stop.assert_called_once()
        app.close_callback.assert_not_called()
        self.assertFalse(app._resetting_data)
        self.assertIn('Данные не удалены',notice.call_args.args[1])
