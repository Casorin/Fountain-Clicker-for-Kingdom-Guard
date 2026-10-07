"""Explicit 100-input diagnostic, independent of automatic fund entry rules."""
import argparse
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import sys
import threading
import time
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.capture import crop_rect
from app.config import AppConfig
from app.hotkeys import CommandBus, EmergencyHotkey
from app.memu_windows import config_for_window, resolve_selections
from app.monitor import PrizeMonitor
from app.profiles import DeviceLeases
from scripts.bounded_click_probe import InputBudget, select_probe_windows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--real-taps', action='store_true', required=True)
    parser.add_argument('--window-uuid', required=True)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--spend-current-balance', action='store_true')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--interval', type=float, default=.125)
    args = parser.parse_args()
    if not args.spend_current_balance and not 1 <= args.limit <= 100:
        parser.error('Input limit must be 1..100')
    if not 1 <= args.seconds <= 300:
        parser.error('Duration must be 1..300 seconds')
    if not .125 <= args.interval <= 2:
        parser.error('Interval must be .125..2 seconds')
    base = replace(AppConfig(), stream_transport_enabled=True)
    window = select_probe_windows(resolve_selections(
        base.runtime_dir/'window_selection.json', base.adb_path), args.window_uuid)[0]
    leases = DeviceLeases(base.runtime_dir/'device_owners')
    leases.acquire([window.serial, 'device:'+window.uuid])
    output = base.runtime_dir/('notification_probe_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    output.mkdir()
    original = config_for_window(base, window)
    config = replace(original, runtime_dir=output, state_path=output/'state.json',
                     user_config_path=original.user_config_path)
    monitor = None
    root = None
    hotkey = None
    stop = threading.Event()
    budget = InputBudget(0 if args.spend_current_balance else args.limit)
    initial_balance = None
    bus = CommandBus(base.runtime_dir/'hotkey_commands')
    samples = []
    reason = 'setup error'
    try:
        root = tk.Tk()
        root.withdraw()
        hotkey = EmergencyHotkey(root, stop.set)
        if not hotkey.registered:
            raise RuntimeError('F9 unavailable: no inputs permitted')
        monitor = PrizeMonitor(config)
        ok, message = monitor.connect()
        if not ok:
            raise RuntimeError(message)
        send = budget.wrap(monitor._stream.tap)
        floor = 0 if args.spend_current_balance else max(10000, monitor.user_range.minimum_gems or 0)
        started = time.monotonic()
        next_tap = started
        last_safe = started
        entered = False
        done_at = None
        screens = 0
        reason = 'duration limit'
        while time.monotonic()-started < args.seconds:
            root.update()
            if stop.is_set() or 'stop' in bus.receive():
                reason = 'external stop'
                break
            context = monitor._capture_context(monitor._now())
            screen, recognition, anchors = context[:3]
            stamp = time.monotonic()
            safe = anchors.button_visible and (anchors.event_screen_ok or
                                               (entered and anchors.continuation_screen_ok))
            if safe:
                entered = True
                last_safe = stamp
            elif stamp-last_safe > 5:
                reason = 'fountain/button safety anchors unavailable'
                break
            monitor.gem_guard.refresh_async(screen, interval=.3,
                frame_time=stamp-getattr(monitor, '_latest_frame_age', 0))
            permitted, wallet_reason = monitor.gem_guard.permits_cached(floor)
            if args.spend_current_balance and initial_balance is None and permitted:
                initial_balance = monitor.gem_guard.estimated
                budget.limit = initial_balance // 100
                print(json.dumps({'initial_balance': initial_balance,
                                  'maximum_inputs': budget.limit}), flush=True)
            if wallet_reason == 'floor':
                reason = 'minimum gem balance reached'
                break
            if safe and permitted and stamp >= next_tap and budget.reserved < budget.limit:
                root.update()
                if stop.is_set() or 'stop' in bus.receive():
                    reason = 'external stop'
                    break
                if not monitor.gem_guard.permits_cached(floor)[0]:
                    continue
                point = monitor._native_point(config.tap_point.x, config.tap_point.y)
                geometry = monitor._screen_geometry
                send(*point, expected_size=(geometry.width, geometry.height))
                monitor.gem_guard.reserve_sent_tap()
                next_tap = time.monotonic()+args.interval
            if len(samples) < 1500:
                name = f'frame_{len(samples):03d}'
                crop_rect(screen, config.prize_crop).save(output/(name+'.png'))
                if len(samples) % 10 == 0:
                    crop_rect(screen, config.daily_label_crop).save(output/(name+'_daily.png'))
                if monitor.state.notification_veto and screens < 16:
                    screen.save(output/(name+'_screen.png'))
                    screens += 1
                samples.append({'file': name+'.png', 'elapsed': round(stamp-started, 3),
                    'sent': budget.sent, 'value': recognition.value,
                    'notification': monitor.state.notification_veto,
                    'screen': anchors.event_screen_ok, 'button': anchors.button_visible,
                    'continuation': anchors.continuation_screen_ok})
            if budget.limit > 0 and budget.reserved >= budget.limit:
                done_at = done_at or stamp
                if stamp-done_at >= 3:
                    reason = 'input budget completed'
                    break
            time.sleep(.02)
    finally:
        if monitor is not None:
            native = getattr(monitor, '_latest_native_screen', None)
            if native is not None:
                from app.screen_geometry import ScreenGeometry
                ScreenGeometry(*native.size).normalize(native).save(output/'final_screen.png')
            monitor.close()
        if hotkey is not None:
            hotkey.close()
        if root is not None:
            root.destroy()
        leases.release()
        result = {'reason': reason, 'sent': budget.sent, 'reserved': budget.reserved,
                  'initial_balance': initial_balance, 'input_limit': budget.limit,
                  'samples': samples, 'inputs': budget.records}
        (output/'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'reason': reason, 'sent': budget.sent, 'output': str(output)}), flush=True)


if __name__ == '__main__':
    main()
