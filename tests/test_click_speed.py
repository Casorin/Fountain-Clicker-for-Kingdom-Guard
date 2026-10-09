import json
from pathlib import Path
import tempfile
import unittest

from app.persistence import UserRangeConfig


class ClickSpeedSettingsTests(unittest.TestCase):
    def test_default_speed_is_five(self):
        self.assertEqual(UserRangeConfig(35000, 500000).clicks_per_second, 5)

    def test_speed_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            UserRangeConfig(35000, 500000, clicks_per_second=3).save(path)
            self.assertEqual(UserRangeConfig.load(path, 35000, 500000).clicks_per_second, 3)

    def test_invalid_and_legacy_settings_use_five(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            for speed in (None, 0, 11, True, '3', 2.5):
                path.write_text(json.dumps({'clicks_per_second': speed}), encoding='utf-8')
                self.assertEqual(UserRangeConfig.load(path, 35000, 500000).clicks_per_second, 5)
            path.write_text('{}', encoding='utf-8')
            self.assertEqual(UserRangeConfig.load(path, 35000, 500000).clicks_per_second, 5)
