from pathlib import Path
import unittest

from app.version import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


class ReleasePackagingTests(unittest.TestCase):
    def test_version_is_11(self):
        self.assertEqual(APP_VERSION, '1.1')

    def test_player_launcher_is_ascii_and_does_not_install_anything(self):
        source = (ROOT/'packaging'/'start.bat').read_bytes()
        text = source.decode('ascii')
        self.assertFalse(source.startswith(b'\xef\xbb\xbf'))
        self.assertIn('pushd "%~dp0"', text)
        self.assertIn('.python\\pythonw.exe', text)
        for forbidden in ('chcp', 'pip install', 'winget', 'py -3'):
            self.assertNotIn(forbidden, text)

    def test_entrypoint_uses_bundled_models_and_no_click_commands(self):
        source = (ROOT/'scripts'/'launch_portable.py').read_text(encoding='utf-8')
        self.assertIn("root / '.models'", source)
        self.assertNotIn('adb.tap', source)
        self.assertNotIn('set_real_mode(True)', source)

    def test_download_instructions_distinguish_player_archive_from_source(self):
        source = (ROOT/'README.md').read_text(encoding='utf-8')
        self.assertIn('Fountain-1.1-Windows.zip', source)
        self.assertIn('Запустить Фонтан.exe', source)
        self.assertIn('Assets', source)
        self.assertIn('Извлечь всё', source)
        self.assertIn('releases/download/v1.1/Fountain-1.1-Windows.zip', source)

    def test_builder_excludes_private_logs(self):
        from scripts.build_portable import ignored
        self.assertEqual(ignored('', ['app.py','secret.log','events.jsonl','__pycache__']),
                         ['secret.log','events.jsonl','__pycache__'])
