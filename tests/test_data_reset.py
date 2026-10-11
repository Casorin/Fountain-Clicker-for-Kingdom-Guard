import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from app import data_reset
from app.data_storage import ResetGuard


class ResetHelperTests(unittest.TestCase):
    def test_real_helper_resets_only_an_isolated_test_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            installation = Path(directory)
            app = installation/'app'
            app.mkdir()
            (app/'__init__.py').touch()
            for name in ('data_reset.py','data_storage.py','single_instance.py'):
                shutil.copy2(data_reset.INSTALLATION_ROOT/'app'/name,app/name)
            (app/'ui.py').write_text(
                "from pathlib import Path\n"
                "root = Path(__file__).resolve().parents[1]\n"
                "assert not (root/'runtime'/'user_config.json').exists()\n"
                "(root/'fresh_started.txt').write_text('started')\n",encoding='utf-8')
            runtime = installation/'runtime'
            runtime.mkdir()
            (runtime/'user_config.json').write_text('old settings')
            asset = installation/'keep_asset.txt'
            asset.write_text('keep')
            sleeper = subprocess.Popen([sys.executable,'-c','import time; time.sleep(.4)'],
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                result = subprocess.run([sys.executable,'-m','app.data_reset','--wait-pid',str(sleeper.pid)],
                    cwd=str(installation),capture_output=True,timeout=10,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                deadline = time.monotonic()+5
                while not (installation/'fresh_started.txt').exists() and time.monotonic()<deadline:
                    time.sleep(.05)
                self.assertEqual((installation/'fresh_started.txt').read_text(),'started')
                self.assertFalse(runtime.exists())
                self.assertEqual(asset.read_text(),'keep')
            finally:
                sleeper.wait(timeout=5)

    def test_helper_waits_for_old_process_before_deleting_and_restarting(self):
        order = Mock()
        with patch('sys.argv',['reset','--wait-pid','123']), \
             patch('app.single_instance.SingleInstanceManager.process_is_running',side_effect=[True,False]) as running, \
             patch('app.data_reset.time.sleep') as sleep, \
             patch('app.data_reset.other_programs_running',return_value=False), \
             patch('app.data_reset.clear_app_data') as clear, \
             patch('app.data_reset.subprocess.Popen') as restart:
            for name,child in [('running',running),('sleep',sleep),('clear',clear),('restart',restart)]:
                order.attach_mock(child,name)
            data_reset.main()
        self.assertEqual([call[0] for call in order.mock_calls],['running','sleep','running','clear','restart'])
        self.assertEqual(restart.call_args.kwargs['env']['KGPM_AUTO_START'],'0')
        self.assertEqual(restart.call_args.args[0][-2:],['-m','app.ui'])

    def test_other_profile_opened_during_shutdown_prevents_deletion(self):
        with patch('sys.argv',['reset','--wait-pid','123']), \
             patch('app.single_instance.SingleInstanceManager.process_is_running',return_value=False), \
             patch('app.data_reset.other_programs_running',return_value=True), \
             patch('app.data_reset.clear_app_data') as clear, \
             patch('app.data_reset.subprocess.Popen') as restart, \
             patch('tkinter.Tk') as root,patch('tkinter.messagebox.showerror') as notice:
            data_reset.main()
        clear.assert_not_called()
        restart.assert_not_called()
        notice.assert_called_once()

    def test_locked_log_is_retried_after_old_process_exits(self):
        with patch('sys.argv',['reset','--wait-pid','123']), \
             patch('app.single_instance.SingleInstanceManager.process_is_running',return_value=False), \
             patch('app.data_reset.other_programs_running',return_value=False), \
             patch('app.data_reset.clear_app_data',side_effect=[PermissionError,None]) as clear, \
             patch('app.data_reset.time.sleep') as sleep, \
             patch('app.data_reset.subprocess.Popen') as restart:
            data_reset.main()
        self.assertEqual(clear.call_count,2)
        sleep.assert_called_once_with(.1)
        restart.assert_called_once()

    def test_nonempty_windows_folder_is_rescanned_before_restart(self):
        import ctypes
        with patch('sys.argv',['reset','--wait-pid','123']), \
             patch('app.single_instance.SingleInstanceManager.process_is_running',return_value=False), \
             patch('app.data_reset.other_programs_running',return_value=False), \
             patch('app.data_reset.clear_app_data',side_effect=[ctypes.WinError(145),None]) as clear, \
             patch('app.data_reset.time.sleep') as sleep, \
             patch('app.data_reset.subprocess.Popen') as restart:
            data_reset.main()
        self.assertEqual(clear.call_count,2)
        sleep.assert_called_once_with(.1)
        restart.assert_called_once()

    def test_new_start_waits_until_reset_releases_its_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            with ResetGuard(installation_root=directory):
                child = subprocess.Popen([sys.executable,'-u','-c',
                    "import sys; from app.data_storage import ResetGuard; "
                    "print('waiting',flush=True); "
                    "guard=ResetGuard(timeout_seconds=5,installation_root=sys.argv[1]); "
                    "guard.__enter__(); print('ready',flush=True); guard.__exit__()",directory],
                    cwd=str(data_reset.INSTALLATION_ROOT),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                try:
                    self.assertEqual(child.stdout.readline().strip(),b'waiting')
                    with self.assertRaises(subprocess.TimeoutExpired):
                        child.communicate(timeout=.2)
                except BaseException:
                    child.kill()
                    child.communicate()
                    raise
            output,error = child.communicate(timeout=10)
            self.assertEqual(child.returncode,0,error.decode(errors='replace'))
            self.assertIn(b'ready',output)

    def test_cleanup_failure_is_visible_and_does_not_claim_success(self):
        with patch('sys.argv',['reset','--wait-pid','123']), \
             patch('app.single_instance.SingleInstanceManager.process_is_running',return_value=False), \
             patch('app.data_reset.other_programs_running',return_value=False), \
             patch('app.data_reset.clear_app_data',side_effect=ValueError('Unsafe path')), \
             patch('app.data_reset.subprocess.Popen') as restart, \
             patch('tkinter.Tk'),patch('tkinter.messagebox.showerror') as notice:
            data_reset.main()
        restart.assert_not_called()
        self.assertIn('Unsafe path',notice.call_args.args[1])

    def test_helper_launch_is_hidden_and_targets_current_process(self):
        with patch('app.data_reset.subprocess.Popen') as process:
            data_reset.launch_reset_helper()
        self.assertEqual(process.call_args.args[0][-2:],['--wait-pid',str(os.getpid())])
        self.assertNotEqual(process.call_args.kwargs['creationflags'],0)
