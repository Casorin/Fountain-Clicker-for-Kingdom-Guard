import json
import shutil
from pathlib import Path
import tempfile
import unittest

from app.adb_runtime import ADB_DIRECTORY, verify_adb_files


class BundledAdbTests(unittest.TestCase):
    def test_official_files_match_pinned_checksums(self):
        self.assertEqual(verify_adb_files(), '37.0.1')

    def test_incomplete_distribution_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'source.json').write_text((ADB_DIRECTORY / 'source.json').read_text(), encoding='utf-8')
            with self.assertRaises(FileNotFoundError):
                verify_adb_files(root)

    def test_unexpected_file_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'source.json').write_text(json.dumps({'files': {'../private': 'x'}}), encoding='utf-8')
            with self.assertRaises(ValueError):
                verify_adb_files(root)

    def test_corrupted_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'adb'
            shutil.copytree(ADB_DIRECTORY, root)
            (root / 'adb.exe').write_bytes(b'incomplete executable')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch: adb.exe'):
                verify_adb_files(root)
