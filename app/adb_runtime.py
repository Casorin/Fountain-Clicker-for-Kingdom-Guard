"""The portable build uses one pinned standard ADB for all emulator providers."""
import hashlib
import json
from pathlib import Path

ADB_DIRECTORY = Path(__file__).resolve().parents[1] / 'assets' / 'adb'


def bundled_adb_path():
    path = ADB_DIRECTORY / 'adb.exe'
    return path if path.is_file() else None


def verify_adb_files(directory=ADB_DIRECTORY):
    metadata = json.loads((directory / 'source.json').read_text(encoding='utf-8'))
    required = {'adb.exe', 'AdbWinApi.dll', 'AdbWinUsbApi.dll', 'NOTICE.txt', 'source.properties'}
    if set(metadata['files']) != required:
        raise ValueError('Invalid ADB manifest')
    for name, checksum in metadata['files'].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != checksum:
            raise ValueError('ADB file checksum mismatch: ' + name)
    return metadata['version']
