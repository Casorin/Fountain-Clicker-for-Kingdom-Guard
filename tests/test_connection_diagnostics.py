import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.connection_diagnostics import preview_error_message
from app.emulator_discovery import find_running_emulator_adb
from app.config import _default_adb_path


class ConnectionDiagnosticsTests(unittest.TestCase):
    def test_finds_adb_beside_ldplayer_in_custom_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'adb.exe').touch()
            with patch('app.emulator_discovery.inventory', return_value={
                'processes': [{'ExecutablePath': str(folder / 'dnplayer.exe')}]
            }):
                self.assertEqual(find_running_emulator_adb(), folder / 'adb.exe')

    def test_config_uses_running_emulator_when_standard_paths_are_missing(self):
        with patch('app.adb_runtime.bundled_adb_path', return_value=None), \
             patch.dict('os.environ', {}, clear=True), patch('app.config.shutil.which', return_value=None), \
             patch('app.config.Path.exists', return_value=False), \
             patch('app.emulator_discovery.find_running_emulator_adb', return_value=Path('custom/adb.exe')):
            self.assertEqual(_default_adb_path(), Path('custom/adb.exe'))

    def test_failure_to_inspect_processes_keeps_safe_fallback(self):
        with patch('app.adb_runtime.bundled_adb_path', return_value=None), \
             patch.dict('os.environ', {}, clear=True), patch('app.config.shutil.which', return_value=None), \
             patch('app.config.Path.exists', return_value=False), \
             patch('app.emulator_discovery.find_running_emulator_adb', side_effect=subprocess.TimeoutExpired('powershell', 20)):
            self.assertEqual(_default_adb_path(), Path('adb.exe'))

    def test_bundled_adb_wins_over_installed_clients(self):
        with patch.dict('os.environ', {}, clear=True), \
             patch('app.adb_runtime.bundled_adb_path', return_value=Path('bundle/adb.exe')), \
             patch('app.config.shutil.which') as system, \
             patch('app.emulator_discovery.find_running_emulator_adb') as running:
            self.assertEqual(_default_adb_path(), Path('bundle/adb.exe'))
            system.assert_not_called()
            running.assert_not_called()

    def test_explicit_developer_override_is_preserved(self):
        with patch.dict('os.environ', {'KGPM_ADB_PATH': 'custom/adb.exe'}, clear=True), \
             patch('app.adb_runtime.bundled_adb_path') as bundled:
            self.assertEqual(_default_adb_path(), Path('custom/adb.exe'))
            bundled.assert_not_called()

    def test_standard_client_wins_over_hd_adb_from_another_running_emulator(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            blue, ld = folder / 'blue', folder / 'ld'
            blue.mkdir()
            ld.mkdir()
            (blue / 'HD-Adb.exe').touch()
            (ld / 'adb.exe').touch()
            with patch('app.emulator_discovery.inventory', return_value={'processes': [
                {'ExecutablePath': str(blue / 'HD-Player.exe')},
                {'ExecutablePath': str(ld / 'dnplayer.exe')}
            ]}):
                self.assertEqual(find_running_emulator_adb(), ld / 'adb.exe')

    def test_errors_are_actionable_without_private_details(self):
        for error, expected in [
            (FileNotFoundError('C:/Users/private/adb.exe'), 'запустить ADB'),
            (RuntimeError('cannot connect to 127.0.0.1:5555'), 'локальную отладку ADB'),
            (RuntimeError('device unauthorized private-account'), 'подтвердите разрешение'),
            (subprocess.TimeoutExpired('private-command', 20), 'не ответил вовремя'),
            (RuntimeError('raw screencap failed private-account'), 'снимок не удалось прочитать'),
            (RuntimeError('secret-token'), 'RuntimeError'),
        ]:
            message = preview_error_message(error)
            self.assertIn(expected, message)
            for private in ('private', '127.0.0.1', 'secret-token'):
                self.assertNotIn(private, message)
