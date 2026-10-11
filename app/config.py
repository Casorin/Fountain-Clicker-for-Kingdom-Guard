from __future__ import annotations

import os
import shutil
import string
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def _default_adb_path() -> Path:
    configured = os.environ.get("KGPM_ADB_PATH", "").strip()
    if configured:
        return Path(configured)
    from app.adb_runtime import bundled_adb_path
    bundled = bundled_adb_path()
    if bundled:
        return bundled
    on_path = shutil.which("adb")
    if on_path:
        return Path(on_path)
    try:
        from app.emulator_discovery import find_running_emulator_adb
        candidate = find_running_emulator_adb()
        if candidate:
            return candidate
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        pass
    for relative in (
            Path("Microvirt") / "MEmu" / "adb.exe",
            Path("Program Files") / "Microvirt" / "MEmu" / "adb.exe",
            Path("LDPlayer") / "LDPlayer9" / "adb.exe",
            Path("LDPlayer") / "LDPlayer14" / "adb.exe",
            Path("LDPlayer") / "LDPlayer4.0" / "adb.exe",
            Path("Program Files") / "BlueStacks_nxt" / "HD-Adb.exe",
        ):
        for drive in string.ascii_uppercase:
            candidate = Path(f"{drive}:\\") / relative
            if candidate.exists():
                return candidate
    return Path("adb.exe")


def _default_adb_serial() -> str:
    return os.environ.get("KGPM_ADB_SERIAL", "127.0.0.1:21503").strip() or "127.0.0.1:21503"


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class TapPoint:
    x: int
    y: int


@dataclass(frozen=True)
class AppConfig:
    stream_transport_enabled: bool = False
    stream_max_fps: int = 15
    stream_max_size: int = 0
    stream_server_path: Path = Path('assets/scrcpy/scrcpy-server-v4.1')
    adb_path: Path = field(default_factory=_default_adb_path)
    adb_serial: str = field(default_factory=_default_adb_serial)
    runtime_dir: Path = Path("runtime")
    screenshot_path: Path = Path("runtime") / "last_screen.png"
    prize_crop_path: Path = Path("runtime") / "last_prize_crop.png"
    button_crop_path: Path = Path("runtime") / "last_button_crop.png"
    title_crop_path: Path = Path("runtime") / "last_title_crop.png"
    debug_dir: Path = Path("runtime") / "debug"
    trigger_dir: Path = Path("runtime") / "triggers"
    reset_diagnostics_dir: Path = Path("runtime") / "reset_diagnostics"
    state_path: Path = Path("runtime") / "state.json"
    instance_state_path: Path = Path("runtime") / "instance_state.json"
    reset_history_path: Path = Path("runtime") / "production_reset_history.json"
    test_reset_history_path: Path = Path("runtime") / "test_reset_history.json"
    user_config_path: Path = Path("runtime") / "user_config.json"
    capture_backend: str = "raw"
    template_dir: Path = Path("assets") / "templates"
    digit_template_dir: Path = Path("assets") / "templates" / "digits"
    digit_template_manifest_path: Path = Path("assets") / "templates" / "digits" / "manifest.json"
    fast_ocr_enabled: bool = False
    fast_prefilter_enabled: bool = False
    title_template_path: Path = Path("assets") / "templates" / "event_title.png"
    screen_anchor_template_path: Path = Path("assets") / "templates" / "screen_anchor.png"
    button_template_path: Path = Path("assets") / "templates" / "wish_button.png"
    layout_template_dir: Path = Path("assets/templates/layout")
    layout_text_threshold: float = 0.90
    prize_label_crop: Rect = Rect(292, 316, 434, 340)
    daily_label_crop: Rect = Rect(278, 395, 452, 417)
    wish_label_crop: Rect = Rect(434, 980, 650, 1009)
    reward_label_crop: Rect = Rect(330, 814, 760, 840)
    session_real_tap_limit: int = 0
    observation_gap_seconds: float = 30.0
    poll_interval_ms: int = 200
    min_prize: int = 200_000
    max_prize: int = 500_000
    test_mode_min_prize: int = 80_000
    test_mode_max_prize: int = 200_000
    test_range_override_enabled: bool = True
    stable_reads_required: int = 2
    unlock_reads_required: int = 3
    reset_cooldown_seconds: int = 120
    click_interval_seconds: float = 0.5
    continuous_clicking: bool = True
    continuous_click_interval_seconds: float = 0.20
    continuous_visibility_grace_seconds: float = 2.0
    continuous_max_taps: int = 150
    burst_size: int = 8
    provisional_check_pause_seconds: float = 2.0
    allow_in_range_fallback: bool = False
    screen_anchor_crop: Rect = Rect(278, 306, 439, 345)
    event_title_crop: Rect = Rect(259, 180, 647, 237)
    prize_crop: Rect = Rect(309, 346, 492, 388)
    button_crop: Rect = Rect(425, 958, 657, 1048)
    tap_point: TapPoint = TapPoint(541, 1003)
    title_match_threshold: float = 0.82
    screen_anchor_threshold: float = 0.90
    button_match_threshold: float = 0.78
    button_gold_ratio_threshold: float = 0.18
    fast_ocr_confidence_threshold: float = 0.84
    fast_prefilter_confidence_threshold: float = 0.78
    full_ocr_heartbeat_seconds: float = 5.0
    fast_prefilter_max_components: int = 8
    fast_prefilter_max_split_rounds: int = 4
    windows_ocr_timeout_seconds: float = 2.5
    notification_dark_ratio_threshold: float = 0.15
    safety_frame_max_age_seconds: float = 0.75
    max_realistic_growth_per_second: int = 40_000
    realistic_growth_slack: int = 8_000
    min_reset_interval_seconds: int = 120
    reset_min_trusted_value: int = 60_000
    reset_low_min_value: int = 5_000
    reset_low_max_value: int = 20_000
    reset_confirmation_max_value: int = 35_000
    reset_low_value_threshold: int = 35_000
    reset_drop_threshold: int = 40_000
    new_cycle_min_rise: int = 20_000
    reset_confirm_reads_required: int = 2
    reset_candidate_timeout_seconds: float = 10.0
