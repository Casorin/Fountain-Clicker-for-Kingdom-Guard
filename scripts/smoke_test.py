from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ["KGPM_DISABLE_TAP_DECISIONS"] = "1"

from app.config import AppConfig
from app.monitor import PrizeMonitor


def main() -> None:
    runtime = ROOT / "runtime" / "fresh_clone_smoke"
    base = AppConfig()
    config = replace(
        base,
        runtime_dir=runtime,
        screenshot_path=runtime / "last_screen.png",
        prize_crop_path=runtime / "last_prize_crop.png",
        button_crop_path=runtime / "last_button_crop.png",
        title_crop_path=runtime / "last_title_crop.png",
        debug_dir=runtime / "debug",
        trigger_dir=runtime / "triggers",
        reset_diagnostics_dir=runtime / "reset_diagnostics",
        state_path=runtime / "state.json",
        instance_state_path=runtime / "instance_state.json",
        reset_history_path=runtime / "production_reset_history.json",
        test_reset_history_path=runtime / "test_reset_history.json",
        user_config_path=runtime / "user_config.json",
    )
    monitor = PrizeMonitor(config)
    connected, message = monitor.connect()
    if not connected:
        raise RuntimeError(message)
    snapshot = monitor.poll_once()
    monitor.close()
    report = {
        "python": sys.executable,
        "adb_path": str(config.adb_path),
        "adb_serial": config.adb_serial,
        "pipeline": type(monitor._ocr_pipeline).__name__,
        "ocr_method": snapshot.recognition.method,
        "value": snapshot.raw_value,
        "screen_ok": snapshot.event_screen_ok,
        "button_ok": snapshot.button_visible,
        "real_mode_armed": monitor.state.real_mode_armed,
        "tap_decisions_enabled": monitor.tap_decisions_enabled,
        "clicked": snapshot.clicked,
        "would_tap": snapshot.would_tap,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if snapshot.clicked or snapshot.would_tap:
        raise AssertionError("Smoke test must not execute or simulate taps")


if __name__ == "__main__":
    main()
