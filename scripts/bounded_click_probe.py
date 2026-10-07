"""Explicitly authorized, lease-protected input probe; no policy overrides."""
import argparse
from collections import Counter, deque
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import shutil
import statistics
import sys
import threading
import time
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.adb_client import AdbError
from app.config import AppConfig
from app.hotkeys import CommandBus, EmergencyHotkey
from app.memu_windows import config_for_window, resolve_selections
from app.monitor import PrizeMonitor
from app.monitor_group import MonitorGroup
from app.profiles import DeviceLeases


class InputBudget:
    def __init__(self, limit):
        self.limit, self.reserved, self.sent = limit, 0, 0
        self.lock = threading.Lock()
        self.records = []

    def wrap(self, send):
        def bounded(*args, **kwargs):
            with self.lock:
                if self.reserved >= self.limit:
                    raise AdbError('Bounded test input limit reached')
                self.reserved += 1
            started = time.monotonic()
            send(*args, **kwargs)
            with self.lock:
                self.sent += 1
                self.records.append({'at': started, 'send_ms': (time.monotonic()-started)*1000})
        return bounded


def stats(values):
    values = sorted(values)
    return {'count': len(values), 'median': statistics.median(values),
            'p95': values[min(len(values)-1, int(len(values)*.95))], 'max': values[-1]} if values else {}


def select_probe_windows(windows, uuid=None):
    if uuid is not None:
        selected = [window for window in windows if window.uuid == uuid]
        if len(selected) != 1:
            raise RuntimeError('The explicitly selected test window is unavailable')
        return selected
    if len(windows) != 3 or [w.name for w in windows[:2]] != ['MEmu', 'MEmu_2']:
        raise RuntimeError('Expected exactly the three previously selected windows')
    return windows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--real-taps', action='store_true', required=True)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--seconds', type=int, default=240)
    parser.add_argument('--window-uuid')
    parser.add_argument('--record-notifications', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100 or not 1 <= args.seconds <= 300:
        parser.error('Limit must be 1..100 and duration 1..300 seconds')
    base = replace(AppConfig(), stream_transport_enabled=True,
                   continuous_click_interval_seconds=.125, continuous_max_taps=0,
                   session_real_tap_limit=args.limit)
    windows = resolve_selections(base.runtime_dir/'window_selection.json', base.adb_path)
    windows = select_probe_windows(windows, args.window_uuid)
    leases = DeviceLeases(base.runtime_dir/'device_owners')
    leases.acquire([identity for w in windows for identity in (w.serial, 'device:'+w.uuid)])
    output = base.runtime_dir/('bounded_probe_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    output.mkdir()
    group = None
    reason = 'setup error'
    root = None
    hotkey = None
    stop = threading.Event()
    counters, latencies, budgets = {}, {}, {}
    bus = CommandBus(base.runtime_dir/'hotkey_commands')
    try:
        root = tk.Tk()
        root.withdraw()
        hotkey = EmergencyHotkey(root, stop.set)
        if not hotkey.registered:
            raise RuntimeError('F9 emergency key unavailable; no test input allowed')
        entries = []
        for window in windows:
            original = config_for_window(base, window)
            folder = output/window.uuid
            folder.mkdir()
            changes = {'runtime_dir': folder}
            for field in ('screenshot_path','prize_crop_path','button_crop_path','title_crop_path',
                          'debug_dir','trigger_dir','reset_diagnostics_dir','state_path',
                          'reset_history_path','test_reset_history_path','user_config_path'):
                changes[field] = folder/getattr(original,field).name
            for field in ('state_path','reset_history_path','user_config_path'):
                source = getattr(original, field)
                if source.exists():
                    shutil.copy2(source, changes[field])
            monitor = PrizeMonitor(replace(original, **changes))
            budget = budgets[window.uuid] = InputBudget(args.limit)
            samples = latencies[window.uuid] = []
            counts = counters[window.uuid] = Counter()
            connect = monitor.connect
            def measured_connect(m=monitor, connect=connect, budget=budget, samples=samples):
                ok, message = connect()
                if ok:
                    m._stream.tap = budget.wrap(m._stream.tap)
                    frame = m._stream.frame
                    def measured_frame(*a, **kw):
                        started = time.monotonic()
                        try:
                            return frame(*a, **kw)
                        finally:
                            samples.append((time.monotonic()-started)*1000)
                    m._stream.frame = measured_frame
                return ok, message
            monitor.connect = measured_connect
            poll = monitor.poll_once
            recording = {'samples': [], 'screens': 0}
            def measured_poll(poll=poll, counts=counts, m=monitor, folder=folder,
                              budget=budget, recording=recording):
                snapshot = poll()
                counts[snapshot.status] += 1
                samples = recording['samples']
                if args.record_notifications and budget.reserved and len(samples) < 300:
                    from app.capture import crop_rect
                    from app.screen_geometry import ScreenGeometry
                    native = getattr(m, '_latest_native_screen', None)
                    if native is not None:
                        screen = ScreenGeometry(*native.size).normalize(native)
                        name = f'notification_{len(samples):03d}'
                        crop_rect(screen, m.config.prize_crop).save(folder/(name+'.png'))
                        if snapshot.notification_veto and recording['screens'] < 12:
                            screen.save(folder/(name+'_screen.png'))
                            recording['screens'] += 1
                        samples.append({'file': name+'.png', 'value': snapshot.trusted_value,
                                        'veto': snapshot.notification_veto, 'status': snapshot.status,
                                        'sent': budget.sent})
                        (folder/'notification_frames.json').write_text(
                            json.dumps(samples, ensure_ascii=False), encoding='utf-8')
                return snapshot
            monitor.poll_once = measured_poll
            entries.append((window,monitor))
        group = MonitorGroup(entries)
        group.set_real_mode(True)
        group.start()
        started, last_print = time.monotonic(), 0
        disarmed = set()
        reason = 'duration limit'
        while time.monotonic()-started < args.seconds:
            root.update()
            for uuid, session in group.sessions.items():
                if budgets[uuid].reserved >= args.limit and uuid not in disarmed:
                    session.request_mode(False)
                    disarmed.add(uuid)
            if all(b.reserved >= args.limit for b in budgets.values()):
                reason = 'input budgets completed'
                break
            if stop.is_set() or 'stop' in bus.receive():
                reason = 'external stop'
                break
            if not group.any_active:
                reason = 'all sessions stopped'
                break
            # Consume UI events so the queue does not impose extra work.
            while not group.events.empty():
                group.events.get_nowait()
            if time.monotonic()-last_print >= 15:
                last_print = time.monotonic()
                print(json.dumps({'elapsed': round(last_print-started), 'windows': [
                    {'name':s.window.name,'sent':budgets[u].sent,'phase':s.monitor.state.phase.value,
                     'status':s.monitor.state.last_status,'frame_waits':s.frame_waits,'fund_waits':s.fund_waits}
                    for u,s in group.sessions.items()]},ensure_ascii=False),flush=True)
            time.sleep(.02)
    finally:
        if hotkey is not None:
            hotkey.close()
        if root is not None:
            root.destroy()
        if group is not None:
            group.emergency_stop()
            group.close()
            result = {'reason': reason, 'windows': []}
            for uuid, session in group.sessions.items():
                records = budgets[uuid].records
                result['windows'].append({'name':session.window.name,'reserved':budgets[uuid].reserved,
                    'sent':budgets[uuid].sent,'frame_wait_ms':stats(latencies[uuid]),
                    'send_ms':stats([r['send_ms'] for r in records]),
                    'tap_gap_seconds':stats([b['at']-a['at'] for a,b in zip(records,records[1:])]),
                    'frame_waits':session.frame_waits,'fund_waits':session.fund_waits,
                    'last_error':session.last_error,'statuses':dict(counters[uuid].most_common(12))})
            (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False),flush=True)
        leases.release()


if __name__ == '__main__':
    main()
