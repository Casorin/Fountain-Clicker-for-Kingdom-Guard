import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.config import AppConfig
from app.hotkeys import CommandBus
from app.profiles import DeviceLeases, profile_config, profile_mutex


class ProfileTests(unittest.TestCase):
    def test_default_keeps_existing_user_files(self):
        base = AppConfig()
        self.assertIs(profile_config(base), base)
        self.assertEqual(profile_mutex('default'), 'Local\\KingdomGuardPrizeMonitor')

    def test_other_fund_has_separate_persistent_files(self):
        base = AppConfig()
        first, second = profile_config(base, 'first'), profile_config(base, 'second')
        for field in ('state_path', 'reset_history_path', 'test_reset_history_path',
                      'user_config_path', 'instance_state_path', 'runtime_dir'):
            self.assertNotEqual(getattr(first, field), getattr(second, field))
            self.assertNotEqual(getattr(first, field), getattr(base, field))
        self.assertEqual(first.prize_crop, base.prize_crop)
        self.assertEqual(first.tap_point, base.tap_point)
        self.assertEqual(first.adb_path, base.adb_path)
        self.assertNotEqual(profile_mutex('first'), profile_mutex('second'))

    def test_path_traversal_rejected(self):
        for name in ('../default', '', 'a/b', 'a\\b', '..', 'x' * 65):
            with self.assertRaises(ValueError):
                profile_config(AppConfig(), name)

    def test_device_conflict_releases_partial_selection(self):
        first, occupied = Mock(), Mock()
        first.try_acquire.return_value = (True, None)
        occupied.try_acquire.return_value = (False, None)
        factory = Mock(side_effect=[first, occupied])
        leases = DeviceLeases(Path('unused'), factory)
        with self.assertRaises(RuntimeError):
            leases.acquire(['serial-a', 'serial-b'])
        first.release.assert_called_once()
        occupied.release.assert_called_once()
        self.assertEqual(leases.held, [])

    def test_same_device_deduplicated_and_released_once(self):
        manager = Mock()
        manager.try_acquire.return_value = (True, None)
        factory = Mock(return_value=manager)
        leases = DeviceLeases(Path('unused'), factory)
        leases.acquire(['serial', 'serial'])
        factory.assert_called_once()
        leases.release()
        leases.release()
        manager.release.assert_called_once()

    def test_hotkeys_reach_both_windows_once(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = CommandBus(folder), CommandBus(folder)
            first.send('stop')
            self.assertEqual(first.receive(), ['stop'])
            self.assertEqual(second.receive(), ['stop'])
            self.assertEqual(first.receive(), [])
            self.assertEqual(second.receive(), [])
            restarted = CommandBus(folder)
            self.assertEqual(restarted.receive(), [])
            second.send('toggle')
            self.assertEqual(restarted.receive(), ['toggle'])


if __name__ == '__main__':
    unittest.main()
