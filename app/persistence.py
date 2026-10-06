from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _dump_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class PersistedState:
    last_reset_at: datetime | None = None
    last_reset_confirmed_at: datetime | None = None
    cooldown_until: datetime | None = None
    last_confirmed_prize: int | None = None
    last_trusted_at: datetime | None = None
    peak_since_reset: int | None = None
    post_reset_baseline: int | None = None
    reset_time_known: bool = False
    unknown_since: datetime | None = None
    reset_episode_locked: bool = False
    reset_growth_hits: int = 0
    reset_growth_last_value: int | None = None
    reset_growth_last_capture_id: str | None = None
    reset_growth_last_at: datetime | None = None
    reset_new_cycle_confirmed: bool = False
    reset_unlock_reason: str = ""
    reset_episode_token: int = 0
    last_recorded_reset_episode_token: int | None = None
    manual_reset_block_real_taps: bool = False

    @classmethod
    def load(cls, path: Path) -> "PersistedState":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls(
            last_reset_at=_parse_dt(data.get("last_reset_at")),
            last_reset_confirmed_at=_parse_dt(data.get("last_reset_confirmed_at")),
            cooldown_until=_parse_dt(data.get("cooldown_until")),
            last_confirmed_prize=data.get("last_confirmed_prize"),
            last_trusted_at=_parse_dt(data.get("last_trusted_at")),
            peak_since_reset=data.get("peak_since_reset"),
            post_reset_baseline=data.get("post_reset_baseline"),
            reset_time_known=bool(data.get("reset_time_known", False)),
            unknown_since=_parse_dt(data.get("unknown_since")),
            reset_episode_locked=bool(data.get("reset_episode_locked", False)),
            reset_growth_hits=int(data.get("reset_growth_hits", 0) or 0),
            reset_growth_last_value=data.get("reset_growth_last_value"),
            reset_growth_last_capture_id=data.get("reset_growth_last_capture_id"),
            reset_growth_last_at=_parse_dt(data.get("reset_growth_last_at")),
            reset_new_cycle_confirmed=bool(data.get("reset_new_cycle_confirmed", False)),
            reset_unlock_reason=str(data.get("reset_unlock_reason", "") or ""),
            reset_episode_token=int(data.get("reset_episode_token", 0) or 0),
            last_recorded_reset_episode_token=data.get("last_recorded_reset_episode_token"),
            manual_reset_block_real_taps=bool(data.get("manual_reset_block_real_taps", False)),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_reset_at": _dump_dt(self.last_reset_at),
            "last_reset_confirmed_at": _dump_dt(self.last_reset_confirmed_at),
            "cooldown_until": _dump_dt(self.cooldown_until),
            "last_confirmed_prize": self.last_confirmed_prize,
            "last_trusted_at": _dump_dt(self.last_trusted_at),
            "peak_since_reset": self.peak_since_reset,
            "post_reset_baseline": self.post_reset_baseline,
            "reset_time_known": self.reset_time_known,
            "unknown_since": _dump_dt(self.unknown_since),
            "reset_episode_locked": self.reset_episode_locked,
            "reset_growth_hits": self.reset_growth_hits,
            "reset_growth_last_value": self.reset_growth_last_value,
            "reset_growth_last_capture_id": self.reset_growth_last_capture_id,
            "reset_growth_last_at": _dump_dt(self.reset_growth_last_at),
            "reset_new_cycle_confirmed": self.reset_new_cycle_confirmed,
            "reset_unlock_reason": self.reset_unlock_reason,
            "reset_episode_token": self.reset_episode_token,
            "last_recorded_reset_episode_token": self.last_recorded_reset_episode_token,
            "manual_reset_block_real_taps": self.manual_reset_block_real_taps,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class ResetEvent:
    timestamp_reset: str
    reset_event_at: str | None = None
    reset_confirmed_at: str | None = None
    last_high_at: str | None = None
    first_low_at: str | None = None
    peak_before_reset: int | None = None
    value_after_reset: int | None = None
    drop_amount: int | None = None
    interval_seconds: int | None = None


@dataclass
class UserRangeConfig:
    test_min_prize: int
    test_max_prize: int
    no_upper_limit: bool = False
    minimum_gems: int | None = None
    start_method: str = "range"
    start_percent: int = 85

    @classmethod
    def load(cls, path: Path, default_min: int, default_max: int) -> "UserRangeConfig":
        if not path.exists():
            return cls(test_min_prize=default_min, test_max_prize=default_max)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(test_min_prize=default_min, test_max_prize=default_max)
        test_min = data.get("test_min_prize", default_min)
        test_max = data.get("test_max_prize", default_max)
        if not isinstance(test_min, int) or not isinstance(test_max, int):
            return cls(test_min_prize=default_min, test_max_prize=default_max)
        floor = data.get("minimum_gems")
        if type(floor) is not int or floor < 0:
            floor = None
        percent = data.get("start_percent", 85)
        if type(percent) is not int or not 1 <= percent <= 100:
            percent = 85
        return cls(test_min_prize=test_min, test_max_prize=test_max,
                   no_upper_limit=data.get("no_upper_limit") is True, minimum_gems=floor,
                   start_method="percent" if data.get("start_method") == "percent" else "range",
                   start_percent=percent)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "test_min_prize": self.test_min_prize,
            "test_max_prize": self.test_max_prize,
            "no_upper_limit": self.no_upper_limit,
            "minimum_gems": self.minimum_gems,
            "start_method": self.start_method,
            "start_percent": self.start_percent,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_reset_history(path: Path) -> list[ResetEvent]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    items: list[ResetEvent] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        timestamp_reset = row.get("timestamp_reset")
        legacy_timestamp = row.get("timestamp")
        if not isinstance(timestamp_reset, str) and not isinstance(legacy_timestamp, str):
            continue
        timestamp_value = timestamp_reset if isinstance(timestamp_reset, str) else legacy_timestamp
        reset_event_at = row.get("reset_event_at")
        if not isinstance(reset_event_at, str):
            reset_event_at = timestamp_value
        reset_confirmed_at = row.get("reset_confirmed_at")
        if not isinstance(reset_confirmed_at, str):
            reset_confirmed_at = None
        last_high_at = row.get("last_high_at")
        if not isinstance(last_high_at, str):
            last_high_at = None
        first_low_at = row.get("first_low_at")
        if not isinstance(first_low_at, str):
            first_low_at = None
        peak_before_reset = row.get("peak_before_reset")
        if not isinstance(peak_before_reset, int):
            peak_before_reset = None
        value_after_reset = row.get("value_after_reset")
        if not isinstance(value_after_reset, int):
            legacy_after = row.get("after_value")
            value_after_reset = legacy_after if isinstance(legacy_after, int) else None
        drop_amount = row.get("drop_amount")
        if not isinstance(drop_amount, int):
            drop_amount = None
        items.append(
            ResetEvent(
                timestamp_reset=timestamp_value,
                reset_event_at=reset_event_at,
                reset_confirmed_at=reset_confirmed_at,
                last_high_at=last_high_at,
                first_low_at=first_low_at,
                peak_before_reset=peak_before_reset,
                value_after_reset=value_after_reset,
                drop_amount=drop_amount,
                interval_seconds=row.get("interval_seconds"),
            )
        )
    return items


def save_reset_history(path: Path, events: list[ResetEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(event) for event in events]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
