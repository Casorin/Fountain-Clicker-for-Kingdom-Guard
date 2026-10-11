"""Restore the pinned open-source ADB binaries from Google's official archive."""
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / 'assets' / 'adb'
    metadata = json.loads((directory / 'source.json').read_text(encoding='utf-8'))
    with urlopen(metadata['url'], timeout=60) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != metadata['archive_sha256']:
        raise ValueError('Upstream archive changed. Review and pin the dependency before updating.')
    with ZipFile(io.BytesIO(archive)) as source:
        files = {name: source.read('platform-tools/' + name) for name in metadata['files']}
    for name, data in files.items():
        if hashlib.sha256(data).hexdigest() != metadata['files'][name]:
            raise ValueError('ADB file checksum mismatch: ' + name)
    for name, data in files.items():
        (directory / name).write_bytes(data)
    print('Verified ADB ' + metadata['version'])


if __name__ == '__main__':
    main()
