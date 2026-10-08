"""Build an allowlisted, relocatable Windows folder using the tested runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.version import APP_VERSION


def ignored(folder, names):
    return [name for name in names if name in {'__pycache__', '.cache', 'site-packages'}
            or name.endswith(('.pyc', '.pyo', '.log', '.jsonl'))]


def build(destination, model_cache):
    if sys.platform != 'win32' or sys.maxsize <= 2**32:
        raise RuntimeError('Build with 64-bit Windows Python')
    bundle = destination / f'Fountain-{APP_VERSION}-Windows'
    if bundle.exists():
        raise FileExistsError(f'Use a new output folder: {bundle}')
    packages = Path(sys.prefix) / 'Lib' / 'site-packages'
    model = model_cache / 'official_models' / 'PP-OCRv6_medium_rec_onnx'
    for item in (packages/'rapidocr', packages/'paddleocr', model/'inference.onnx'):
        if not item.exists():
            raise FileNotFoundError(f'Required build input is missing: {item}')
    bundle.mkdir(parents=True)
    python = bundle / '.python'
    python.mkdir()
    base = Path(sys.base_prefix)
    for item in base.iterdir():
        if item.is_file() and (item.suffix in {'.exe', '.dll'} or item.name == 'LICENSE.txt'):
            shutil.copy2(item, python/item.name)
    for name in ('DLLs', 'Lib', 'tcl'):
        shutil.copytree(base/name, python/name, ignore=ignored)
    shutil.copytree(packages, python/'Lib'/'site-packages', ignore=ignored)
    shutil.copytree(ROOT/'app', bundle/'app', ignore=ignored)
    shutil.copytree(ROOT/'assets', bundle/'assets', ignore=ignored)
    shutil.copytree(model, bundle/'.models'/'official_models'/model.name, ignore=ignored)
    (bundle/'scripts').mkdir()
    shutil.copy2(ROOT/'scripts'/'launch_portable.py', bundle/'scripts'/'launch_portable.py')
    shutil.copy2(ROOT/'packaging'/'start.bat', bundle/'Запустить Фонтан.bat')
    compile_launcher(bundle)
    shutil.copy2(ROOT/'packaging'/'FIRST_START.txt', bundle/'СНАЧАЛА ПРОЧИТАЙТЕ.txt')
    shutil.copy2(ROOT/'THIRD_PARTY_NOTICES.md', bundle/'THIRD_PARTY_NOTICES.md')
    manifest = {'version': APP_VERSION, 'python': sys.version.split()[0], 'files': {}}
    for item in sorted(bundle.rglob('*')):
        if item.is_file():
            manifest['files'][item.relative_to(bundle).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    (bundle/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    archive = destination/f'Fountain-{APP_VERSION}-Windows.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for item in sorted(bundle.rglob('*')):
            if item.is_file():
                output.write(item, item.relative_to(destination))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n', encoding='ascii')
    print(archive)


def compile_launcher(bundle):
    import os
    compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'
    if not compiler.exists():
        raise FileNotFoundError('Windows .NET Framework compiler is required for the launcher')
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:anycpu',
                    '/reference:System.Windows.Forms.dll',
                    '/win32icon:' + str(ROOT/'assets'/'fountain.ico'),
                    '/out:' + str(bundle/'Запустить Фонтан.exe'),
                    str(ROOT/'packaging'/'Launcher.cs')], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-cache', type=Path, default=Path.home()/'.paddlex')
    args = parser.parse_args()
    build(args.output.resolve(), args.model_cache.resolve())
