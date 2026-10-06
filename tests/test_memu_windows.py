from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import AppConfig
from app.memu_windows import MemuWindow, parse_window_info, config_for_window, save_selection, resolve_selection


class MemuTests(unittest.TestCase):
    def test_port_from_actual_forward_not_instance_number(self):
        info = 'VMState="running"\nForwarding(0)="ADB,tcp,127.0.0.1,21523,10.0.2.15,5555"'
        self.assertEqual(parse_window_info('MEmu_2', 'abc', info), MemuWindow('MEmu_2', 'abc', '127.0.0.1:21523'))
        self.assertIsNone(parse_window_info('x', 'abc', info.replace('running', 'poweroff')))
        self.assertIsNone(parse_window_info('x', 'abc', info.replace('127.0.0.1', '10.0.0.1')))

    def test_history_and_state_separate_range_shared(self):
        base = AppConfig()
        first = config_for_window(base, MemuWindow('MEmu', 'abc', '127.0.0.1:21503'))
        second = config_for_window(base, MemuWindow('MEmu_2', 'def', '127.0.0.1:21523'))
        self.assertEqual(first.state_path, base.state_path)
        self.assertNotEqual(first.state_path, second.state_path)
        self.assertNotEqual(first.reset_history_path, second.reset_history_path)
        self.assertEqual(first.user_config_path, second.user_config_path)
        self.assertEqual(first.instance_state_path, second.instance_state_path)

    def test_saved_selection_uses_uuid_and_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'selection.json'
            original = MemuWindow('second', 'def', '127.0.0.1:21523')
            save_selection(path, original)
            moved = replace(original, serial='127.0.0.1:21543')
            with patch('app.memu_windows.discover_windows', return_value=[moved]):
                self.assertEqual(resolve_selection(path, Path('adb.exe')), moved)
            with patch('app.memu_windows.discover_windows', return_value=[MemuWindow('first', 'abc', original.serial)]):
                self.assertIsNone(resolve_selection(path, Path('adb.exe')))
