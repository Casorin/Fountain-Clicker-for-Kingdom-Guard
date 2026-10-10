"""Read-only discovery of running MEmu instances from their actual ADB forwards."""
from dataclasses import dataclass, replace
import json
import re
import subprocess
import string
from pathlib import Path

from app.adb_client import AdbClient
from app.capture import save_screen


@dataclass(frozen=True)
class MemuWindow:
    name: str
    uuid: str
    serial: str
    provider: str = 'MEmu'


def parse_window_info(name, uuid, info):
    if 'VMState="running"' not in info:
        return None
    for rule in re.findall(r'^Forwarding\(\d+\)="([^"]+)"', info, re.M):
        fields = rule.split(',')
        if len(fields) == 6 and fields[1] == 'tcp' and fields[5] == '5555':
            if fields[2] not in ('127.0.0.1', 'localhost', ''):
                continue
            if fields[3].isdigit() and 0 < int(fields[3]) < 65536:
                return MemuWindow(name, uuid, '127.0.0.1:' + fields[3])
    return None


def memu_managers(adb_path, processes):
    candidates = {Path(adb_path).parent.parent / 'MEmuHyperv' / 'MEmuManage.exe'}
    for process in processes:
        if process.get('Name', '').lower() in {'memu.exe', 'memuheadless.exe'} and process.get('ExecutablePath'):
            folder = Path(process['ExecutablePath']).parent
            candidates.update((folder.parent / 'MEmuHyperv' / 'MEmuManage.exe',
                               folder / 'MEmuManage.exe'))
    for drive in string.ascii_uppercase:
        for folder in ('Microvirt', 'Program Files/Microvirt'):
            candidates.add(Path(f'{drive}:/') / folder / 'MEmuHyperv/MEmuManage.exe')
    return sorted({candidate.resolve() for candidate in candidates if candidate.is_file()})


def discover_windows(adb_path, diagnostics=None):
    from app.emulator_discovery import inventory, discover_extra_windows
    from app.connection_diagnostics import preview_error_message
    errors = diagnostics if diagnostics is not None else []
    try:
        data = inventory()
    except Exception as error:
        data = {'processes': [], 'ports': []}
        errors.append(('Поиск окон', preview_error_message(error)))
    def read(manage, *args):
        result = subprocess.run([str(manage), *args], capture_output=True, timeout=10,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError('Не удалось прочитать список окон MEmu.')
        return result.stdout.decode('utf-8', errors='replace')
    windows = []
    for manage in memu_managers(adb_path, data.get('processes', [])):
        try:
            listing = read(manage, 'list', 'runningvms')
            for name, uuid in re.findall(r'^"(.+)"\s+\{([0-9a-fA-F-]+)\}', listing, re.M):
                try:
                    window = parse_window_info(name, uuid, read(manage, 'showvminfo', uuid, '--machinereadable'))
                    if window and window.uuid not in {item.uuid for item in windows}:
                        windows.append(window)
                except Exception as error:
                    errors.append(('MEmu', preview_error_message(error)))
        except Exception as error:
            errors.append(('MEmu', preview_error_message(error)))
    windows.extend(discover_extra_windows(data, errors))
    if not any(w.provider == 'MEmu' for w in windows) and any(p.get('Name', '').lower() in {'memu.exe', 'memuheadless.exe'} for p in data.get('processes', [])):
        errors.append(('MEmu', 'MEmu запущен, но список его окон не получен. Дождитесь полной загрузки и обновите снимки. Если не помогло, отправьте технический отчёт.'))
    if len({w.serial for w in windows}) != len(windows):
        raise RuntimeError('Неоднозначные адреса эмуляторов. Выбор остановлен для безопасности.')
    return windows


def preview_window(adb_path, window):
    adb = AdbClient(adb_path, window.serial)
    try:
        adb.connect()
        if window.serial not in adb.devices():
            raise RuntimeError('Окно недоступно. Проверьте локальную отладку ADB и дождитесь загрузки эмулятора.')
        return save_screen(adb, Path('unused.png'), backend='raw', save=False)
    finally:
        adb.close_shell()


def config_for_window(base, window):
    # Retain existing user's history for the original default instance only.
    if window.serial == '127.0.0.1:21503' and window.name == 'MEmu':
        return replace(base, adb_serial=window.serial)
    folder = base.runtime_dir / 'windows' / window.uuid
    changes = {'adb_serial': window.serial, 'runtime_dir': folder,
               'stream_max_fps': 15 if window.provider in {'LDPlayer','BlueStacks'} else base.stream_max_fps,
               'stream_max_size': 1080 if window.provider == 'LDPlayer' else base.stream_max_size}
    for field in ('screenshot_path', 'prize_crop_path', 'button_crop_path', 'title_crop_path',
                  'debug_dir', 'trigger_dir', 'reset_diagnostics_dir', 'state_path',
                  'reset_history_path', 'test_reset_history_path'):
        changes[field] = folder / getattr(base, field).name
    # Range settings remain shared; state/history are not shared.
    return replace(base, **changes)


def save_selection(path, window):
    save_selections(path, [window])


def save_selections(path, windows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({'windows': [{'uuid': w.uuid, 'name': w.name} for w in windows]}, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def resolve_selection(path, adb_path):
    windows = resolve_selections(path, adb_path)
    return windows[0] if windows else None


def resolve_selections(path, adb_path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    requested = data.get('windows', [data])
    if len({w['uuid'] for w in requested}) != len(requested):
        raise ValueError('Duplicate MEmu selection')
    available = {w.uuid: w for w in discover_windows(adb_path)}
    if not requested or any(w['uuid'] not in available for w in requested):
        return []
    return [available[w['uuid']] for w in requested]
