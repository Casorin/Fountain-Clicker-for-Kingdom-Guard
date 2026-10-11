"""Read-only discovery from running vendor processes and their actual ADB ports."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
import winreg


def read_command(arguments):
    result = subprocess.run(arguments, capture_output=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Не удалось прочитать список эмуляторов')
    return result.stdout.decode('utf-8-sig', errors='replace')


def inventory():
    script = """$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new();
$p=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -in 'dnplayer.exe','HD-Player.exe','MEmu.exe','MEmuHeadless.exe'} |
 Select-Object ProcessId,Name,ExecutablePath);
$t=@(Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess);
@{processes=$p;ports=$t} | ConvertTo-Json -Depth 4 -Compress"""
    return json.loads(read_command(['powershell.exe', '-NoProfile', '-Command', script]))


def find_running_emulator_adb():
    data = inventory()
    candidates = []
    for process in data.get('processes', []):
        executable = process.get('ExecutablePath')
        if not executable:
            continue
        folder = Path(executable).parent
        for name in ('adb.exe', 'HD-Adb.exe'):
            candidate = folder / name
            if candidate.is_file():
                candidates.append(candidate)
    # Vendor HD-Adb is a fallback, not the client for other running emulators.
    return next((path for path in candidates if path.name.lower() == 'adb.exe'),
                candidates[0] if candidates else None)


def ld_windows(processes, ports, reader=read_command):
    from app.memu_windows import MemuWindow
    windows = []
    folders = {Path(p['ExecutablePath']).parent for p in processes
               if p['Name'].lower() == 'dnplayer.exe' and p.get('ExecutablePath')}
    for folder in sorted(folders):
        console = next((folder / name for name in ('ldconsole.exe', 'dnconsole.exe') if (folder / name).exists()), None)
        if console is None:
            continue
        for line in reader([str(console), 'list2']).splitlines():
            fields = line.split(',')
            if len(fields) < 7 or fields[4] != '1' or not fields[6].isdigit():
                continue
            candidates = [p for p in ports if p['OwningProcess'] == int(fields[6])
                          and 5555 <= p['LocalPort'] < 6000 and p['LocalPort'] % 2 == 1]
            if len(candidates) != 1:
                continue
            port = candidates[0]
            # BlueStacks may bind 127.0.0.1 on the same port as LDPlayer's wildcard.
            host = '127.0.0.2' if port['LocalAddress'] == '0.0.0.0' else port['LocalAddress']
            if not host.startswith('127.'):
                continue
            identity = hashlib.sha256(str(folder.resolve()).lower().encode()).hexdigest()[:12]
            windows.append(MemuWindow('LDPlayer · ' + fields[1], 'ld-' + identity + '-' + fields[0],
                                      f'{host}:{port["LocalPort"]}', 'LDPlayer'))
    return windows


def parse_blue_config(text, running_ports):
    from app.memu_windows import MemuWindow
    values = dict(re.findall(r'^([^=]+)="(.*)"$', text, re.M))
    windows = []
    for key, value in values.items():
        match = re.fullmatch(r'bst\.instance\.([^.]+)\.adb_port', key)
        if not match or not value.isdigit() or int(value) not in running_ports:
            continue
        instance = match[1]
        name = values.get('bst.instance.' + instance + '.display_name', instance)
        windows.append(MemuWindow('BlueStacks · ' + name, 'blue-' + instance,
                                  '127.0.0.1:' + value, 'BlueStacks'))
    return windows


def blue_windows(processes, ports):
    pids = {p['ProcessId'] for p in processes if p['Name'].lower() == 'hd-player.exe'}
    running_ports = {p['LocalPort'] for p in ports if p['OwningProcess'] in pids
                     and p['LocalAddress'] in {'127.0.0.1', '0.0.0.0'}}
    if not running_ports:
        return []
    for name in ('SOFTWARE\\BlueStacks_nxt', 'SOFTWARE\\WOW6432Node\\BlueStacks_nxt'):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, name) as key:
                folder = Path(winreg.QueryValueEx(key, 'DataDir')[0])
            for candidate in (folder / 'bluestacks.conf', folder.parent / 'bluestacks.conf'):
                if candidate.exists():
                    return parse_blue_config(candidate.read_text(encoding='utf-8'), running_ports)
        except OSError:
            continue
    return []


def discover_extra_windows(data=None, diagnostics=None):
    data = inventory() if data is None else data
    windows = []
    from app.connection_diagnostics import preview_error_message
    for provider, discover in (('LDPlayer', ld_windows), ('BlueStacks', blue_windows)):
        try:
            found = discover(data.get('processes', []), data.get('ports', []))
            windows.extend(found)
            process_name = 'dnplayer.exe' if provider == 'LDPlayer' else 'hd-player.exe'
            if not found and diagnostics is not None and any(p.get('Name', '').lower() == process_name for p in data.get('processes', [])):
                diagnostics.append((provider, 'Эмулятор запущен, но доступные подключения не найдены. Включите локальную отладку ADB в каждом нужном окне, дождитесь загрузки и обновите снимки.'))
        except Exception as error:
            if diagnostics is not None:
                diagnostics.append((provider, preview_error_message(error)))
    return windows
