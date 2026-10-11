from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo
from collections import deque
import json
import os
import shutil
import threading
import time

from PIL import Image

from app.adb_client import AdbClient, AdbError
from app.stream_transport import FreshFrameUnavailable
from app.capture import crop_rect, save_screen
from app.config import AppConfig
from app.diagnostics_writer import DiagnosticsWriter
from app.persistence import (
    PersistedState,
    ResetEvent,
    UserRangeConfig,
    load_reset_history,
    save_reset_history,
)
from app.fast_ocr import FastOcrResult, PrefilterResult, prefilter_range, recognize_digits_from_templates
from app.recognition import (
    RecognitionResult,
    save_prize_ocr_debug_variants,
)
from app.production_ocr import (
    EngineReading,
    NotificationAssessment,
    NotificationVetoTracker,
    ProductionOcrEngines,
    ProductionOcrPipeline,
    ProductionOcrResult,
)
from app.vision import AnchorStatus, analyze_anchors


class MonitorPhase(str, Enum):
    RESET_TIME_UNKNOWN = "RESET_TIME_UNKNOWN"
    WAITING = "WAITING"
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    ACTIVE_CLICKING = "ACTIVE_CLICKING"
    CHECKING_AFTER_BURST = "CHECKING_AFTER_BURST"
    RESET_COOLDOWN = "RESET_COOLDOWN"
    PAUSED = "PAUSED"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class OcrStatus(str, Enum):
    VISIBLE = "Число видно"
    OBSCURED = "Закрыто уведомлением"
    TIMEOUT = "Windows OCR timeout"
    ERROR = "Ошибка распознавания"
    SKIPPED = "Windows OCR пропущен prefilter"

@dataclass
class MonitorState:
    phase: MonitorPhase = MonitorPhase.RESET_TIME_UNKNOWN
    ocr_status: OcrStatus = OcrStatus.ERROR
    last_value: int | None = None
    raw_ocr_value: int | None = None
    trusted_value: int | None = None
    last_trust_reason: str = ""
    last_status: str = "Ожидание"
    candidate_value: int | None = None
    candidate_hits: int = 0
    candidate_capture_id: str | None = None
    candidate_at: datetime | None = None
    reset_candidate_hits: int = 0
    reset_candidate_value: int | None = None
    test_mode: bool = True
    real_mode_armed: bool = False
    last_reset_at: datetime | None = None
    last_reset_confirmed_at: datetime | None = None
    cooldown_until: datetime | None = None
    reset_time_known: bool = False
    unknown_since: datetime | None = None
    last_confirmed_prize: int | None = None
    last_trusted_at: datetime | None = None
    reset_last_high_at: datetime | None = None
    reset_first_low_at: datetime | None = None
    reset_first_low_value: int | None = None
    reset_first_low_capture_id: str | None = None
    reset_pre_reset_peak: int | None = None
    peak_since_reset: int | None = None
    post_reset_baseline: int | None = None
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
    burst_taps_done: int = 0
    total_taps: int = 0
    real_taps: int = 0
    virtual_taps: int = 0
    next_click_at: datetime | None = None
    checking_until: datetime | None = None
    last_full_ocr_at: datetime | None = None
    last_prefilter_digit_count: int | None = None
    last_prefilter_first_digit: int | None = None
    test_range_override_enabled: bool = True
    growth_candidate_value: int | None = None
    growth_candidate_at: datetime | None = None
    notification_veto: bool = False
    notification_heavy: bool = False
    notification_recovery_hits: int = 0
    last_tap_sent_at: datetime | None = None
    continuous_session_active: bool = False
    session_last_visible_at: datetime | None = None
    session_last_value: int | None = None
    session_reset_suspected: bool = False
    anchor_recovery_started_at: datetime | None = None
    start_requires_new_reset: bool = False
    fast_observation_active: bool = False


@dataclass(frozen=True)
class PollSnapshot:
    timestamp: str
    value: int | None
    raw_value: int | None
    trusted_value: int | None
    status: str
    phase: MonitorPhase
    ocr_status: OcrStatus
    confirmation_hits: int
    in_range: bool
    event_screen_ok: bool
    button_visible: bool
    title_score: float
    screen_anchor_score: float
    button_score: float
    button_gold_ratio: float
    title_text: str
    button_text: str
    prefilter_status: str
    prefilter_confidence: float
    prefilter_digit_count: int | None
    prefilter_first_digit: int | None
    recognition: RecognitionResult
    clicked: bool
    would_tap: bool
    diagnostics_dir: str | None
    last_reset_at: str
    last_reset_confirmed_at: str
    seconds_since_reset: int | None
    cooldown_remaining: int | None
    active_burst_taps: int
    total_taps: int
    reset_history_rows: list[tuple[str, str, str, str]]
    reset_average_label: str
    reset_min_label: str
    reset_max_label: str
    reset_since_history_label: str
    since_reset_label: str
    cooldown_label: str
    mode_banner: str
    target_range_label: str
    editable_test_range_label: str
    real_taps_label: str
    tap_events: list[str]
    capture_ms: float
    fast_observation_ms: float
    authoritative_ocr_ms: float | None
    authoritative_ocr_ran: bool
    notification_veto: bool
    notification_heavy: bool
    notification_recovery_hits: int
    paddle_control_ran: bool
    continuation_screen_ok: bool = False


class PrizeMonitor:
    def __init__(self, config: AppConfig, now_provider: Callable[[], datetime] | None = None) -> None:
        self.config = config
        self.adb = AdbClient(config.adb_path, config.adb_serial)
        self._now_provider = now_provider or datetime.now
        self.state = MonitorState()
        self._stream = None
        self._stream_sequence = -1
        self._tap_cancel = threading.Event()
        from app.popup_dismissal import PopupDismissal
        self._popup_dismissal = PopupDismissal()
        self._current_popup = None
        self.state.test_range_override_enabled = config.test_range_override_enabled
        self.user_range = UserRangeConfig.load(
            self.config.user_config_path,
            self.config.test_mode_min_prize,
            self.config.test_mode_max_prize,
        )
        self.reset_history: list[ResetEvent] = load_reset_history(self.config.reset_history_path)
        self.recent_observations: deque[dict[str, object]] = deque(maxlen=40)
        self.recent_prize_crops: deque[Image.Image] = deque(maxlen=5)
        self._latest_screen: Image.Image | None = None
        self._latest_native_screen = None
        self._screen_geometry = None
        self._latest_prize_crop: Image.Image | None = None
        self._latest_capture_completed_at: datetime | None = None
        self._last_production_ocr: ProductionOcrResult | None = None
        self._post_burst_paddle_pending = False
        self._diagnostics_writer = DiagnosticsWriter(max_queue_size=20)
        self._last_diagnostics_enqueue_accepted = True
        self._last_full_diagnostics_at = None
        self._ocr_pipeline = ProductionOcrPipeline(
            engines=ProductionOcrEngines(),
            notification_tracker=NotificationVetoTracker(config.notification_dark_ratio_threshold),
            compatible_growth=config.realistic_growth_slack,
        )
        from app.gem_guard import GemGuard
        self.gem_guard = GemGuard(self._ocr_pipeline.engines)
        self._async_wallet = True
        self.tap_decisions_enabled = os.environ.get("KGPM_DISABLE_TAP_DECISIONS", "0") != "1"
        self._percentage_reference_after = None
        self._last_observation_at = None
        self._load_persisted_state()

    def _now(self) -> datetime:
        return self._now_provider()

    def _load_persisted_state(self) -> None:
        persisted = PersistedState.load(self.config.state_path)
        now = self._now()
        self.state.last_reset_at = persisted.last_reset_at
        self.state.last_reset_confirmed_at = persisted.last_reset_confirmed_at
        self.state.cooldown_until = persisted.cooldown_until
        self.state.last_confirmed_prize = persisted.last_confirmed_prize
        self.state.last_trusted_at = persisted.last_trusted_at
        self.state.peak_since_reset = persisted.peak_since_reset
        self.state.post_reset_baseline = persisted.post_reset_baseline
        self.state.reset_time_known = persisted.reset_time_known
        self.state.unknown_since = persisted.unknown_since or now
        self.state.reset_episode_locked = persisted.reset_episode_locked
        self.state.reset_growth_hits = persisted.reset_growth_hits
        self.state.reset_growth_last_value = persisted.reset_growth_last_value
        self.state.reset_growth_last_capture_id = persisted.reset_growth_last_capture_id
        self.state.reset_growth_last_at = persisted.reset_growth_last_at
        self.state.reset_new_cycle_confirmed = persisted.reset_new_cycle_confirmed
        self.state.reset_unlock_reason = persisted.reset_unlock_reason
        self.state.reset_episode_token = persisted.reset_episode_token
        self.state.last_recorded_reset_episode_token = persisted.last_recorded_reset_episode_token
        self.state.manual_reset_block_real_taps = persisted.manual_reset_block_real_taps
        if self.state.last_trusted_at and now.timestamp() - self.state.last_trusted_at.timestamp() > self.config.observation_gap_seconds:
            self._discard_stale_observation(now)
        latest_reset = self._latest_percentage_reset()
        if latest_reset is not None and now.timestamp() - datetime.fromisoformat(latest_reset.timestamp_reset).timestamp() >= 1800:
            self._percentage_reference_after = now
            self._discard_stale_observation(now)
        if (
            self.state.reset_episode_locked
            and self.state.post_reset_baseline is None
            and self.reset_history
        ):
            self.state.post_reset_baseline = self.reset_history[0].value_after_reset
            if self.state.post_reset_baseline is not None:
                # Legacy state has no independent-frame evidence for its stored peak.
                # Start a fresh trusted sequence without reconstructing a missed reset.
                self.state.last_confirmed_prize = None
                self.state.last_trusted_at = None
                self.state.peak_since_reset = self.state.post_reset_baseline
                self.state.reset_growth_hits = 0
                self.state.reset_growth_last_value = None
                self.state.reset_growth_last_capture_id = None
                self.state.reset_growth_last_at = None
                self.state.reset_new_cycle_confirmed = False
                self.state.reset_unlock_reason = "LOCKED: migrated legacy state; waiting for confirmed new high cycle"
        if self.state.cooldown_until and self.state.cooldown_until > now:
            self.state.phase = MonitorPhase.RESET_COOLDOWN
        elif self.state.reset_time_known:
            self.state.phase = MonitorPhase.WAITING
        else:
            self.state.phase = MonitorPhase.RESET_TIME_UNKNOWN

    def _restore_recent_reset_timer(self, now: datetime) -> bool:
        state = self.state
        if state.manual_reset_block_real_taps or state.start_requires_new_reset:
            return False
        if state.last_reset_at is None or state.last_reset_confirmed_at is None:
            return False
        elapsed = now.timestamp()-state.last_reset_at.timestamp()
        if not 0 <= elapsed <= 900:
            return False
        state.reset_time_known = True
        deadline = state.last_reset_at + timedelta(seconds=self.config.reset_cooldown_seconds)
        state.cooldown_until = deadline if deadline > now else None
        state.phase = MonitorPhase.RESET_COOLDOWN if state.cooldown_until else MonitorPhase.WAITING
        return True

    def _discard_stale_observation(self, now: datetime) -> None:
        # A gap is not evidence of a reset. Keep history/deadlines, discard only
        # the old live comparison baseline and restart the observation period.
        self.state.continuous_session_active = False
        self.state.last_confirmed_prize = None
        self.state.last_trusted_at = None
        self.state.peak_since_reset = None
        self.state.post_reset_baseline = None
        self.state.reset_growth_hits = 0
        self.state.reset_growth_last_value = None
        self.state.reset_growth_last_capture_id = None
        self.state.reset_growth_last_at = None
        self.state.reset_new_cycle_confirmed = False
        self.state.reset_time_known = False
        self.state.unknown_since = now
        self.state.next_click_at = None
        self.state.checking_until = None
        self._clear_candidate()
        self._clear_reset_candidate()
        self.state.phase = MonitorPhase.RESET_TIME_UNKNOWN
        self._restore_recent_reset_timer(now)

    def _expire_interrupted_observation(self, now: datetime) -> None:
        previous_frame_at = getattr(self, '_last_observation_at', None)
        last_trusted_at = self.state.last_trusted_at
        interrupted = (previous_frame_at is not None and
                       now.timestamp() - previous_frame_at.timestamp() > self.config.observation_gap_seconds)
        expired = (last_trusted_at is not None and
                   now.timestamp() - last_trusted_at.timestamp() >= 1800)
        if interrupted or expired:
            self._discard_stale_observation(now)

    def _save_persisted_state(self) -> None:
        PersistedState(
            last_reset_at=self.state.last_reset_at,
            last_reset_confirmed_at=self.state.last_reset_confirmed_at,
            cooldown_until=self.state.cooldown_until,
            last_confirmed_prize=self.state.last_confirmed_prize,
            last_trusted_at=self.state.last_trusted_at,
            peak_since_reset=self.state.peak_since_reset,
            post_reset_baseline=self.state.post_reset_baseline,
            reset_time_known=self.state.reset_time_known,
            unknown_since=self.state.unknown_since,
            reset_episode_locked=self.state.reset_episode_locked,
            reset_growth_hits=self.state.reset_growth_hits,
            reset_growth_last_value=self.state.reset_growth_last_value,
            reset_growth_last_capture_id=self.state.reset_growth_last_capture_id,
            reset_growth_last_at=self.state.reset_growth_last_at,
            reset_new_cycle_confirmed=self.state.reset_new_cycle_confirmed,
            reset_unlock_reason=self.state.reset_unlock_reason,
            reset_episode_token=self.state.reset_episode_token,
            last_recorded_reset_episode_token=self.state.last_recorded_reset_episode_token,
            manual_reset_block_real_taps=self.state.manual_reset_block_real_taps,
        ).save(self.config.state_path)

    @staticmethod
    def _local_zone() -> ZoneInfo:
        return ZoneInfo("Europe/Samara")

    @staticmethod
    def _format_duration(seconds: int | None) -> str:
        if seconds is None:
            return "Неизвестно"
        hours, remainder = divmod(max(0, seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours} ч {minutes:02d} мин {secs:02d} сек"
        if minutes:
            return f"{minutes} мин {secs:02d} сек"
        return f"{secs} сек"

    @staticmethod
    def _event_time_for_history(event: ResetEvent) -> str:
        return event.reset_event_at or event.timestamp_reset

    def _history_rows(self) -> list[tuple[str, str, str, str]]:
        rows: list[tuple[str, str, str, str]] = []
        for index, event in enumerate(self.reset_history[:10], start=1):
            dt = datetime.fromisoformat(self._event_time_for_history(event))
            local = dt.astimezone(self._local_zone())
            interval = self._format_duration(self._interval_seconds_for_index(index - 1))
            peak = str(event.peak_before_reset) if event.peak_before_reset is not None else "нет данных"
            rows.append((str(index), local.strftime("%H:%M:%S"), peak, interval))
        return rows

    def _history_stats(self) -> tuple[str, str, str]:
        intervals = [
            seconds
            for index in range(len(self.reset_history))
            if (seconds := self._interval_seconds_for_index(index)) is not None
        ]
        if len(intervals) < 1:
            return ("недостаточно данных", "недостаточно данных", "недостаточно данных")
        average = int(sum(intervals) / len(intervals))
        return (
            self._format_duration(average),
            self._format_duration(min(intervals)),
            self._format_duration(max(intervals)),
        )

    def _history_since_reset_label(self, now: datetime) -> str:
        if not self.reset_history:
            return "неизвестно"
        try:
            newest = datetime.fromisoformat(self._event_time_for_history(self.reset_history[0])).astimezone(self._local_zone())
        except ValueError:
            return "неизвестно"
        return self._format_duration(max(0, int((now.astimezone(self._local_zone()) - newest).total_seconds())))

    def _interval_seconds_for_index(self, index: int) -> int | None:
        if index < 0 or index >= len(self.reset_history):
            return None
        if index >= len(self.reset_history) - 1:
            return self.reset_history[index].interval_seconds
        try:
            current = datetime.fromisoformat(self._event_time_for_history(self.reset_history[index]))
            previous = datetime.fromisoformat(self._event_time_for_history(self.reset_history[index + 1]))
        except ValueError:
            return self.reset_history[index].interval_seconds
        return max(0, int((current - previous).total_seconds()))

    def _backups_dir(self) -> Path:
        return self.config.runtime_dir / "backups"

    def _history_audit_log_path(self) -> Path:
        return self.config.runtime_dir / "manual_history_actions.log"

    def _backup_reset_history(self, reason: str) -> Path:
        backups_dir = self._backups_dir()
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = self._now().astimezone(self._local_zone()).strftime("%Y%m%d_%H%M%S")
        target = backups_dir / f"production_reset_history_before_{reason}_{stamp}.json"
        if self.config.reset_history_path.exists():
            shutil.copy2(self.config.reset_history_path, target)
        else:
            target.write_text("[]", encoding="utf-8")
        return target

    def _log_history_action(
        self,
        action: str,
        deleted_reset_timestamp: str | None = None,
        deleted_peak: int | None = None,
    ) -> None:
        log_path = self._history_audit_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": self._now().astimezone(self._local_zone()).isoformat(),
            "action": action,
            "deleted_reset_timestamp": deleted_reset_timestamp,
            "deleted_peak": deleted_peak,
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _recalculate_reset_history_intervals(self, events: list[ResetEvent]) -> list[ResetEvent]:
        recalculated: list[ResetEvent] = []
        for index, event in enumerate(events):
            interval_seconds: int | None = None
            if index + 1 < len(events):
                try:
                    current = datetime.fromisoformat(self._event_time_for_history(event))
                    previous = datetime.fromisoformat(self._event_time_for_history(events[index + 1]))
                    interval_seconds = max(0, int((current - previous).total_seconds()))
                except ValueError:
                    interval_seconds = event.interval_seconds
            recalculated.append(
                ResetEvent(
                    timestamp_reset=event.timestamp_reset,
                    reset_event_at=event.reset_event_at,
                    reset_confirmed_at=event.reset_confirmed_at,
                    last_high_at=event.last_high_at,
                    first_low_at=event.first_low_at,
                    peak_before_reset=event.peak_before_reset,
                    value_after_reset=event.value_after_reset,
                    drop_amount=event.drop_amount,
                    interval_seconds=interval_seconds,
                )
            )
        return recalculated

    def delete_reset_history_entry(self, visible_index: int) -> tuple[bool, str]:
        if visible_index < 0 or visible_index >= len(self.reset_history):
            return False, "Выбранная запись не найдена"
        backup_path = self._backup_reset_history("manual_delete")
        deleted = self.reset_history.pop(visible_index)
        self.reset_history = self._recalculate_reset_history_intervals(self.reset_history)
        save_reset_history(self.config.reset_history_path, self.reset_history)
        self._log_history_action("manual_delete", deleted.timestamp_reset, deleted.peak_before_reset)
        return (
            True,
            f"Удалена запись {deleted.timestamp_reset} (peak={deleted.peak_before_reset if deleted.peak_before_reset is not None else 'нет данных'}). "
            f"Backup: {backup_path}",
        )

    def clear_reset_history(self) -> tuple[bool, str]:
        backup_path = self._backup_reset_history("manual_clear_all")
        deleted_events = list(self.reset_history)
        self.reset_history = []
        save_reset_history(self.config.reset_history_path, self.reset_history)
        for event in deleted_events:
            self._log_history_action("manual_delete", event.timestamp_reset, event.peak_before_reset)
        self._log_history_action("manual_clear_all", None, None)
        return True, f"Вся production-история очищена. Backup: {backup_path}"

    def _format_since_reset_label(self, now: datetime) -> str:
        seconds = self._seconds_since_reset(now)
        if seconds is None:
            return "—"
        return self._format_duration(seconds)

    def _append_reset_history(
        self,
        peak_before_reset: int | None,
        value_after_reset: int | None,
        event_at: datetime,
        confirmed_at: datetime,
        last_high_at: datetime | None,
        first_low_at: datetime | None,
    ) -> None:
        if self.state.last_recorded_reset_episode_token == self.state.reset_episode_token:
            return
        aware_event = event_at.astimezone(self._local_zone())
        aware_confirmed = confirmed_at.astimezone(self._local_zone())
        if self.reset_history:
            try:
                newest = datetime.fromisoformat(self._event_time_for_history(self.reset_history[0])).astimezone(self._local_zone())
                gap_seconds = int((aware_event - newest).total_seconds())
                if gap_seconds < self.config.min_reset_interval_seconds:
                    self.state.last_status = (
                        f"Reset history blocked: impossible interval {gap_seconds}с < "
                        f"{self.config.min_reset_interval_seconds}с"
                    )
                    return
            except ValueError:
                pass
        previous_dt = (
            datetime.fromisoformat(self._event_time_for_history(self.reset_history[0])).astimezone(self._local_zone())
            if self.reset_history
            else None
        )
        interval_seconds = int((aware_event - previous_dt).total_seconds()) if previous_dt else None
        if self.reset_history and self._event_time_for_history(self.reset_history[0]) == aware_event.isoformat():
            return
        if self.reset_history:
            try:
                newest = datetime.fromisoformat(self._event_time_for_history(self.reset_history[0])).astimezone(self._local_zone())
                if abs((aware_event - newest).total_seconds()) < 1:
                    return
            except ValueError:
                pass
        drop_amount = None
        if peak_before_reset is not None and value_after_reset is not None:
            drop_amount = peak_before_reset - value_after_reset
        event = ResetEvent(
            timestamp_reset=aware_event.isoformat(),
            reset_event_at=aware_event.isoformat(),
            reset_confirmed_at=aware_confirmed.isoformat(),
            last_high_at=last_high_at.astimezone(self._local_zone()).isoformat() if last_high_at else None,
            first_low_at=first_low_at.astimezone(self._local_zone()).isoformat() if first_low_at else None,
            peak_before_reset=peak_before_reset,
            value_after_reset=value_after_reset,
            drop_amount=drop_amount,
            interval_seconds=interval_seconds,
        )
        self.reset_history.insert(0, event)
        from app.data_storage import HISTORY_LIMIT
        del self.reset_history[HISTORY_LIMIT:]
        self.state.last_recorded_reset_episode_token = self.state.reset_episode_token
        save_reset_history(self.config.reset_history_path, self.reset_history)

    def connect(self) -> tuple[bool, str]:
        try:
            connect_output = self.adb.connect()
            devices = self.adb.devices()
        except AdbError as exc:
            return False, str(exc)

        if self.config.adb_serial not in devices:
            return False, f"ADB подключён, но устройство {self.config.adb_serial} не видно"
        if self.config.stream_transport_enabled:
            from app.stream_transport import StreamTransport
            self._stream = StreamTransport(self.adb, self.config.stream_server_path,
                                           max_fps=getattr(self.config,'stream_max_fps',30),
                                           max_size=getattr(self.config,'stream_max_size',0))
            try:
                self._stream.start()
                self._stream_sequence = -1
            except Exception as exc:
                self._stream.close()
                self._stream = None
                return False, f"Видеопоток не запущен: {exc}"
        return True, connect_output or "Подключено"

    def set_real_mode(self, enabled: bool) -> tuple[bool, str]:
        if not enabled:
            self._tap_cancel.set()
        else:
            self._tap_cancel.clear()
        if enabled and self.config.session_real_tap_limit and self.state.real_taps >= self.config.session_real_tap_limit:
            return False, "Достигнут лимит настоящих нажатий за сеанс"
        self._clear_candidate()
        self.state.continuous_session_active = False
        self.state.next_click_at = None
        self.state.checking_until = None
        self.state.burst_taps_done = 0
        if self.state.phase in {MonitorPhase.ACTIVE_CLICKING, MonitorPhase.CANDIDATE, MonitorPhase.CONFIRMED, MonitorPhase.CHECKING_AFTER_BURST}:
            self.state.phase = MonitorPhase.WAITING
        self.state.real_mode_armed = enabled
        self.state.test_mode = not enabled
        self.state.last_status = "Реальный режим включён" if enabled else "Тестовый режим включён"
        if enabled and not self.state.manual_reset_block_real_taps:
            now = self._now()
            reset = self.state.last_reset_at
            if reset is not None and (now.timestamp()-reset.timestamp() > 900 or reset > now):
                self.state.start_requires_new_reset = True
                self.state.reset_time_known = False
                self.state.phase = MonitorPhase.RESET_TIME_UNKNOWN
                self.state.last_status = 'Последнее обнуление было более 15 минут назад. Ждём новое обнуление.'
            elif reset is None or self.state.last_reset_confirmed_at is None:
                self.state.start_requires_new_reset = True
                self.state.reset_time_known = False
                self.state.phase = MonitorPhase.RESET_TIME_UNKNOWN
                self.state.last_status = 'Нет подтверждённого времени обнуления. Ждём новое обнуление.'
            elif self._restore_recent_reset_timer(now):
                self.state.last_status = ('Ждём окончания двух минут после обнуления'
                                         if self.state.cooldown_until else
                                         'Таймер обнуления подтверждён. Проверяем правило кликов.')
        return True, self.state.last_status

    def pause(self) -> None:
        self._tap_cancel.set()
        self.state.fast_observation_active = False
        if hasattr(self, '_observation_activity'):
            self._observation_activity.observe(screen_ok=False, notification=False,
                                               balance=None, reset_at=self.state.last_reset_confirmed_at,
                                               paused=True)
        self.state.continuous_session_active = False
        self.state.next_click_at = None
        self.state.phase = MonitorPhase.PAUSED
        self.state.last_status = "Мониторинг приостановлен"

    def emergency_stop(self) -> None:
        self.state.fast_observation_active = False
        self.set_real_mode(False)
        self.state.phase = MonitorPhase.EMERGENCY_STOP
        self.state.last_status = "Аварийная остановка"

    def resume(self) -> None:
        self._tap_cancel.clear()
        writer = getattr(self, "_diagnostics_writer", None)
        if writer is not None and not writer.is_alive:
            self._diagnostics_writer = DiagnosticsWriter(max_queue_size=20)
        if self.state.phase in {MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP}:
            self.state.phase = (
                MonitorPhase.WAITING if self.state.reset_time_known else MonitorPhase.RESET_TIME_UNKNOWN
            )
            self.state.last_status = "Мониторинг возобновлён"

    def reset_lock(self) -> None:
        now = self._now()
        self.state.fast_observation_active = False
        self.state.continuous_session_active = False
        self.state.last_value = None
        self.state.raw_ocr_value = None
        self.state.trusted_value = None
        self._clear_candidate()
        self.state.reset_candidate_hits = 0
        self.state.reset_candidate_value = None
        self.state.last_reset_at = None
        self.state.last_reset_confirmed_at = None
        self.state.cooldown_until = None
        self.state.last_confirmed_prize = None
        self.state.last_trusted_at = None
        self.state.reset_last_high_at = None
        self.state.reset_first_low_at = None
        self.state.reset_first_low_value = None
        self.state.reset_first_low_capture_id = None
        self.state.reset_pre_reset_peak = None
        self.state.peak_since_reset = None
        self.state.post_reset_baseline = None
        self.state.ocr_status = OcrStatus.ERROR
        self.state.reset_episode_locked = False
        self.state.reset_growth_hits = 0
        self.state.reset_growth_last_value = None
        self.state.reset_growth_last_capture_id = None
        self.state.reset_growth_last_at = None
        self.state.reset_new_cycle_confirmed = False
        self.state.reset_unlock_reason = ""
        self.state.last_trust_reason = ""
        self.state.reset_episode_token += 1
        self.state.last_recorded_reset_episode_token = None
        self.state.burst_taps_done = 0
        self.state.total_taps = 0
        self.state.next_click_at = None
        self.state.checking_until = None
        self.state.last_full_ocr_at = None
        self.state.last_prefilter_digit_count = None
        self.state.last_prefilter_first_digit = None
        self.state.growth_candidate_value = None
        self.state.growth_candidate_at = None
        self.recent_prize_crops.clear()
        if self.state.real_mode_armed:
            self.state.reset_time_known = False
            self.state.unknown_since = now
            self.state.manual_reset_block_real_taps = True
            self.state.phase = MonitorPhase.RESET_TIME_UNKNOWN
            self.state.last_status = (
                "Состояние сброшено вручную: реальные tap заблокированы до нового достоверного reset"
            )
        else:
            self.state.reset_time_known = True
            self.state.unknown_since = None
            self.state.manual_reset_block_real_taps = False
            self.state.phase = MonitorPhase.WAITING
            self.state.last_status = "Состояние мониторинга сброшено вручную"
        self._save_persisted_state()

    def target_range_for_mode(self, real_mode: bool | None = None) -> tuple[int, int]:
        _active_real_mode = self.state.real_mode_armed if real_mode is None else real_mode
        if self.user_range.start_method == "percent":
            threshold = self.percentage_start_threshold()
            return (threshold if threshold is not None else 2**63, 2**63-1)
        return self.user_range.test_min_prize, (2**63-1 if self.user_range.no_upper_limit else self.user_range.test_max_prize)

    def _latest_percentage_reset(self):
        valid = []
        for event in self.reset_history:
            try:
                stamp = datetime.fromisoformat(event.timestamp_reset).timestamp()
            except (ValueError, TypeError):
                continue
            valid.append((stamp, event))
        return max(valid, key=lambda item: item[0])[1] if valid else None

    def percentage_start_threshold(self) -> int | None:
        event = self._latest_percentage_reset()
        if event is None or type(event.peak_before_reset) is not int or event.peak_before_reset <= 0:
            return None
        after = getattr(self, '_percentage_reference_after', None)
        if after is not None and datetime.fromisoformat(event.timestamp_reset).timestamp() < after.timestamp():
            return None
        # Round up: never start below the selected percentage.
        threshold = (event.peak_before_reset * self.user_range.start_percent + 99) // 100
        return max(threshold, self.user_range.percent_minimum_prize or 0)

    def editable_test_range_label(self) -> str:
        return self.target_range_label()

    def update_test_range(self, min_value: int, max_value: int, *, no_upper_limit: bool | None = None,
                          minimum_gems: int | None = None, update_gem_limit: bool = False,
                          start_method: str | None = None, start_percent: int | None = None,
                          percent_minimum_prize: int | None = None,
                          update_percent_minimum: bool = False,
                          clicks_per_second: int | None = None) -> tuple[bool, str]:
        if clicks_per_second is not None and (type(clicks_per_second) is not int or not 1 <= clicks_per_second <= 10):
            return False, "Скорость должна быть целым числом от 1 до 10 кликов в секунду"
        if update_percent_minimum and percent_minimum_prize is not None and (type(percent_minimum_prize) is not int or percent_minimum_prize < 0):
            return False, "Минимальный фонд должен быть целым неотрицательным числом"
        if start_method is not None and start_method not in {"range", "percent"}:
            return False, "Выберите начало по диапазону или по проценту"
        if start_percent is not None and (type(start_percent) is not int or not 1 <= start_percent <= 100):
            return False, "Процент должен быть целым числом от 1 до 100"
        if min_value < 1000:
            return False, "Минимальное значение должно быть не меньше 1000"
        if max_value > 999_999:
            return False, "Максимальное значение должно быть не больше 999999"
        unlimited = self.user_range.no_upper_limit if no_upper_limit is None else no_upper_limit
        if not unlimited and min_value >= max_value:
            return False, "Минимальное значение должно быть меньше максимального"
        if update_gem_limit and minimum_gems is not None and (type(minimum_gems) is not int or minimum_gems < 0):
            return False, "Остаток самоцветов должен быть целым неотрицательным числом"
        self.user_range = replace(self.user_range, test_min_prize=min_value, test_max_prize=max_value,
                                  clicks_per_second=clicks_per_second if clicks_per_second is not None else self.user_range.clicks_per_second,
                                  no_upper_limit=self.user_range.no_upper_limit if no_upper_limit is None else no_upper_limit,
                                  minimum_gems=minimum_gems if update_gem_limit else self.user_range.minimum_gems,
                                  start_method=start_method or self.user_range.start_method,
                                  start_percent=start_percent if start_percent is not None else self.user_range.start_percent,
                                  percent_minimum_prize=percent_minimum_prize if update_percent_minimum else self.user_range.percent_minimum_prize)
        self.user_range.save(self.config.user_config_path)
        self.state.continuous_session_active = False
        self._clear_candidate()
        self.state.next_click_at = None
        self.state.burst_taps_done = 0
        if self.state.phase in {MonitorPhase.ACTIVE_CLICKING, MonitorPhase.CANDIDATE, MonitorPhase.CONFIRMED}:
            self.state.phase = MonitorPhase.WAITING
        self.state.last_status = f"Сохранено начало кликов: {self.target_range_label()}"
        return True, self.state.last_status

    def is_target_value(self, value: int, real_mode: bool | None = None) -> bool:
        lower, upper = self.target_range_for_mode(real_mode)
        return lower <= value <= upper

    def mode_banner(self) -> str:
        if self.state.real_mode_armed:
            return "РЕАЛЬНЫЙ ДИАПАЗОН"
        return "ТЕСТОВЫЙ РЕЖИМ"

    def target_range_label(self) -> str:
        if self.user_range.start_method == "percent":
            threshold = self.percentage_start_threshold()
            if threshold is None:
                return f"{self.user_range.start_percent}% · ждём новое обнуление"
            return f"{self.user_range.start_percent}% · от {threshold:,}".replace(",", " ")
        lower, upper = self.target_range_for_mode()
        if self.user_range.no_upper_limit:
            return f"от {lower:,} · без верхнего предела".replace(",", " ")
        return f"{lower:,}–{upper:,}".replace(",", " ")

    def real_taps_label(self) -> str:
        if self.state.real_mode_armed:
            if self.state.manual_reset_block_real_taps:
                return "РЕАЛЬНЫЕ TAP ЗАБЛОКИРОВАНЫ ДО НОВОГО RESET"
            return "РЕАЛЬНЫЕ TAP РАЗРЕШЕНЫ"
        return "РЕАЛЬНЫЕ TAP ЗАПРЕЩЕНЫ"

    def _append_observation(
        self,
        now: datetime,
        recognition: RecognitionResult,
        anchors: AnchorStatus,
        prefilter: PrefilterResult,
    ) -> None:
        frame_timestamp = now.astimezone(self._local_zone()).isoformat()
        capture_id = now.astimezone(self._local_zone()).strftime("%Y%m%d_%H%M%S_%f")
        self.recent_observations.append(
            {
                "timestamp": frame_timestamp,
                "capture_id": capture_id,
                "frame_timestamp": frame_timestamp,
                "ocr_source": f"{recognition.method}:{recognition.variant_name}",
                "raw_value": self.state.raw_ocr_value,
                "trusted_value": self.state.trusted_value,
                "ocr_method": recognition.method,
                "ocr_status": self.state.ocr_status.value,
                "screen_ok": anchors.event_screen_ok,
                "continuation_screen_ok": anchors.continuation_screen_ok,
                "button_ok": anchors.button_visible,
                "prefilter_status": prefilter.status,
                "prefilter_reason": prefilter.reason,
                "prefilter_digit_count": prefilter.digit_count,
                "trust_reason": self.state.last_trust_reason,
                "confirmed_peak": self.state.peak_since_reset,
                "post_reset_baseline": self.state.post_reset_baseline,
                "reset_candidate_hits": self.state.reset_candidate_hits,
                "reset_episode_locked": self.state.reset_episode_locked,
                "last_reset_at": self.state.last_reset_at.isoformat() if self.state.last_reset_at else None,
                "seconds_since_reset": self._seconds_since_reset(now),
                "new_cycle_high_hits": self.state.reset_growth_hits,
                "new_cycle_confirmed": self.state.reset_new_cycle_confirmed,
                "unlock_reason": self.state.reset_unlock_reason,
            }
        )

    def _save_reset_diagnostics(
        self,
        now: datetime,
        label: str,
        recognition: RecognitionResult | None = None,
        anchors: AnchorStatus | None = None,
        prefilter: PrefilterResult | None = None,
        reset_event_at: datetime | None = None,
        reset_confirmed_at: datetime | None = None,
    ) -> Path:
        target_dir = self.config.reset_diagnostics_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = now.astimezone(self._local_zone()).strftime("%Y%m%d_%H%M%S_%f")
        path = target_dir / f"{stamp}_{label}.json"
        screen_path = target_dir / f"{stamp}_{label}_screen.png"
        crop_path = target_dir / f"{stamp}_{label}_prize_crop.png"
        if self._latest_screen is not None:
            self._latest_screen.save(screen_path)
        if self._latest_prize_crop is not None:
            self._latest_prize_crop.save(crop_path)
        payload = {
            "label": label,
            "capture_id": stamp,
            "frame_timestamp": now.astimezone(self._local_zone()).isoformat(),
            "ocr_source": (
                f"{recognition.method}:{recognition.variant_name}" if recognition else None
            ),
            "screen_path": str(screen_path) if screen_path.exists() else None,
            "prize_crop_path": str(crop_path) if crop_path.exists() else None,
            "last_reset_at": self.state.last_reset_at.isoformat() if self.state.last_reset_at else None,
            "last_reset_confirmed_at": (
                self.state.last_reset_confirmed_at.isoformat() if self.state.last_reset_confirmed_at else None
            ),
            "confirmed_peak": self.state.peak_since_reset,
            "post_reset_baseline": self.state.post_reset_baseline,
            "last_confirmed_prize": self.state.last_confirmed_prize,
            "last_trusted_value": self.state.last_confirmed_prize,
            "last_trusted_at": self.state.last_trusted_at.isoformat() if self.state.last_trusted_at else None,
            "last_high_at": self.state.reset_last_high_at.isoformat() if self.state.reset_last_high_at else None,
            "first_low_value": self.state.reset_first_low_value,
            "first_low_at": self.state.reset_first_low_at.isoformat() if self.state.reset_first_low_at else None,
            "first_low_capture_id": self.state.reset_first_low_capture_id,
            "pre_reset_peak": self.state.reset_pre_reset_peak,
            "reset_event_at": reset_event_at.isoformat() if reset_event_at else None,
            "reset_confirmed_at": reset_confirmed_at.isoformat() if reset_confirmed_at else None,
            "confirmation_delay_seconds": (
                round((reset_confirmed_at - reset_event_at).total_seconds(), 3)
                if reset_event_at and reset_confirmed_at
                else None
            ),
            "raw_ocr_value": self.state.raw_ocr_value,
            "trusted_value": self.state.trusted_value,
            "trust_reason": self.state.last_trust_reason,
            "reset_candidate_hits": self.state.reset_candidate_hits,
            "reset_candidate_value": self.state.reset_candidate_value,
            "reset_episode_locked": self.state.reset_episode_locked,
            "seconds_since_reset": self._seconds_since_reset(now),
            "new_cycle_high_hits": self.state.reset_growth_hits,
            "new_cycle_confirmed": self.state.reset_new_cycle_confirmed,
            "unlock_reason": self.state.reset_unlock_reason,
            "ocr_method": recognition.method if recognition else None,
            "ocr_raw_text": recognition.raw_text if recognition else None,
            "ocr_normalized_text": recognition.normalized_text if recognition else None,
            "ocr_fast_reason": recognition.fast_reason if recognition else None,
            "prefilter_status": prefilter.status if prefilter else None,
            "prefilter_reason": prefilter.reason if prefilter else None,
            "prefilter_timings_ms": prefilter.timings_ms if prefilter else None,
            "screen_ok": anchors.event_screen_ok if anchors else None,
            "button_ok": anchors.button_visible if anchors else None,
            "observations": list(self.recent_observations),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _update_peak_tracking(self, value: int, recognition: RecognitionResult) -> None:
        if recognition.method in {"prefilter_skip", "windows_ocr_timeout"}:
            return
        if self.state.peak_since_reset is None or value > self.state.peak_since_reset:
            self.state.peak_since_reset = value

    def _looks_like_reset_transition(
        self,
        previous_value: int,
        new_value: int,
    ) -> bool:
        return new_value < previous_value

    def _is_reset_confirmation_frame(self, value: int | None) -> bool:
        return value is not None and self.state.reset_candidate_hits > 0

    def _save_outlier_diagnostics(
        self,
        screen: Image.Image,
        prize_crop: Image.Image,
        recognition: RecognitionResult,
        now: datetime,
        reason: str,
    ) -> Path:
        target_dir = self.config.debug_dir / "ocr_outliers" / now.astimezone(self._local_zone()).strftime("%Y%m%d_%H%M%S_%f")
        target_dir.mkdir(parents=True, exist_ok=True)
        screen.save(target_dir / "screen.png")
        prize_crop.save(target_dir / "prize_crop.png")
        save_prize_ocr_debug_variants(prize_crop, target_dir)
        (target_dir / "decision.txt").write_text(
            "\n".join(
                [
                    f"raw_value={recognition.value}",
                    f"raw_text={recognition.normalized_text}",
                    f"variant={recognition.variant_name}",
                    f"method={recognition.method}",
                    f"reason={reason}",
                    f"candidates={recognition.fast_reason}",
                    f"last_trusted={self.state.last_confirmed_prize}",
                    f"last_trusted_at={self.state.last_trusted_at.isoformat() if self.state.last_trusted_at else ''}",
                ]
            ),
            encoding="utf-8",
        )
        return target_dir

    def _resolve_trusted_value(self, raw_value: int | None, now: datetime) -> tuple[int | None, str]:
        if raw_value is None:
            return None, "no raw OCR value"
        previous_trusted = self.state.last_confirmed_prize
        if previous_trusted is None or self.state.last_trusted_at is None:
            self.state.growth_candidate_value = None
            self.state.growth_candidate_at = None
            return raw_value, "accepted initial trusted value"
        if raw_value == previous_trusted:
            self.state.growth_candidate_value = None
            self.state.growth_candidate_at = None
            return raw_value, "same as previous trusted value"
        if raw_value < previous_trusted:
            self.state.growth_candidate_value = None
            self.state.growth_candidate_at = None
            if self._looks_like_reset_transition(previous_trusted, raw_value):
                return raw_value, "accepted as reset low value"
            if self._is_reset_confirmation_frame(raw_value):
                return raw_value, "accepted as reset confirmation continuation"
            return None, f"rejected backward jump {previous_trusted}->{raw_value}"
        if self._is_reset_confirmation_frame(raw_value):
            return raw_value, "accepted as reset growth continuation"

        elapsed = max(0.10, (now - self.state.last_trusted_at).total_seconds())
        allowed_growth = int(self.config.max_realistic_growth_per_second * elapsed + self.config.realistic_growth_slack)
        growth = raw_value - previous_trusted
        if growth <= self.config.realistic_growth_slack:
            self.state.growth_candidate_value = None
            self.state.growth_candidate_at = None
            return raw_value, f"accepted ordinary growth +{growth}"
        if growth <= allowed_growth:
            pending = self.state.growth_candidate_value
            pending_at = self.state.growth_candidate_at
            if pending is not None and pending_at is not None:
                confirmation_elapsed = max(0.10, (now - pending_at).total_seconds())
                confirmation_growth = raw_value - pending
                confirmation_limit = int(
                    self.config.max_realistic_growth_per_second * confirmation_elapsed
                    + self.config.realistic_growth_slack
                )
                if 0 <= confirmation_growth <= confirmation_limit:
                    self.state.growth_candidate_value = None
                    self.state.growth_candidate_at = None
                    return raw_value, f"accepted growth after independent frame {pending}->{raw_value}"
            self.state.growth_candidate_value = raw_value
            self.state.growth_candidate_at = now
            return None, (
                f"suspicious growth pending independent frame: "
                f"{previous_trusted}->{raw_value}"
            )
        return None, f"rejected OCR outlier growth +{raw_value - previous_trusted} > {allowed_growth}"

    def _update_reset_episode_lock(
        self,
        value: int | None,
        now: datetime | None = None,
        capture_id: str | None = None,
    ) -> None:
        if not self.state.reset_episode_locked or value is None:
            return

        now = now or self._now()
        capture_id = capture_id or now.astimezone(self._local_zone()).strftime("%Y%m%d_%H%M%S_%f")
        seconds_since_reset = self._seconds_since_reset(now)
        if capture_id == self.state.reset_growth_last_capture_id:
            return

        self.state.reset_growth_hits += 1
        self.state.reset_growth_last_value = value
        self.state.reset_growth_last_capture_id = capture_id
        self.state.reset_growth_last_at = now

        interval_elapsed = (
            seconds_since_reset is not None
            and seconds_since_reset >= self.config.min_reset_interval_seconds
        )
        self.state.reset_new_cycle_confirmed = self.state.reset_growth_hits >= 3 and interval_elapsed
        if not interval_elapsed:
            self.state.reset_unlock_reason = "LOCKED: waiting for 120s"
            return

        self.state.reset_unlock_reason = "LOCKED: 120s passed, waiting for independent trusted frames"
        if self.state.reset_new_cycle_confirmed:
            self.state.reset_episode_locked = False
            self.state.reset_unlock_reason = "UNLOCKED: confirmed new high cycle after previous reset"
            self._clear_reset_candidate()
            self.state.reset_episode_token += 1
            self._save_reset_diagnostics(now, "episode_unlocked")
            self._save_persisted_state()

    def _paddle_control_reasons(self, rapid: EngineReading) -> tuple[str, ...]:
        value = rapid.value
        if value is None:
            return ()
        reasons: list[str] = []
        previous = self.state.last_confirmed_prize
        if self.is_target_value(value) and self.state.phase in {
            MonitorPhase.WAITING,
            MonitorPhase.CANDIDATE,
            MonitorPhase.CONFIRMED,
        }:
            reasons.append("click_range_confirmation")
        if self._post_burst_paddle_pending:
            reasons.append("post_burst_check")
        if self.state.reset_candidate_hits > 0:
            reasons.append("potential_reset")
        if previous is not None:
            if value < previous:
                reasons.append("backward_or_reset")
            elif value - previous > self.config.realistic_growth_slack:
                reasons.append("suspicious_growth")
        return tuple(dict.fromkeys(reasons))

    def _native_point(self, x, y):
        geometry = getattr(self, '_screen_geometry', None)
        return geometry.to_native(x, y) if geometry is not None else (x, y)

    def _capture_context(
        self,
        now: datetime,
    ) -> tuple[Image.Image, RecognitionResult, AnchorStatus, PrefilterResult, float, float, float | None, bool]:
        import time

        started_capture = time.perf_counter()
        frame_age = 0.0
        if self._stream is not None:
            frame = self._stream.frame(after=self._stream_sequence)
            self._stream_sequence = frame.sequence
            screen = frame.image
            frame_age = max(0.0,time.monotonic()-frame.received_at)
        else:
            screen = save_screen(self.adb, self.config.screenshot_path, backend=self.config.capture_backend, save=False)
        capture_ms = (time.perf_counter() - started_capture) * 1000.0
        from app.screen_geometry import ScreenGeometry
        geometry = ScreenGeometry(*screen.size)
        if self._screen_geometry is not None and geometry != self._screen_geometry:
            self._clear_candidate()
            self.state.continuous_session_active = False
            self.state.next_click_at = None
            if self.state.phase in {MonitorPhase.CANDIDATE, MonitorPhase.CONFIRMED,
                                    MonitorPhase.ACTIVE_CLICKING, MonitorPhase.CHECKING_AFTER_BURST}:
                self.state.phase = MonitorPhase.WAITING
            self.gem_guard.checked_at = -float('inf')
            self.gem_guard.balance = self.gem_guard.estimated = None
        self._latest_native_screen = screen.copy()
        try:
            screen = geometry.normalize(screen)
        except ValueError as exc:
            self.state.next_click_at = None
            raise FreshFrameUnavailable(str(exc)) from exc
        self._screen_geometry = geometry
        anchor_config = replace(self.config, layout_template_dir=geometry.template_directory(self.config.layout_template_dir))
        self._current_popup = self._popup_dismissal.detect(screen)

        prize_crop = crop_rect(screen, self.config.prize_crop)
        capture_id = now.astimezone(self._local_zone()).strftime("%Y%m%d_%H%M%S_%f")
        self._latest_screen = screen.copy()
        if self._current_popup is not None:
            # Dialog numbers must never enter wallet, prize, or reset recognition.
            self._latest_capture_completed_at = self._now()-timedelta(seconds=frame_age)
            empty = Image.new("RGB", (1, 1))
            return (screen, RecognitionResult("", "", None, "popup", 0.0, "popup", False),
                    AnchorStatus(False, False, 0, 0, 0, 0, "", "", "popup", "popup", empty, empty),
                    PrefilterResult("NOT_RUN", 0, None, None, "popup", {}, False, ""),
                    capture_ms, 0.0, None, False)
        self._latest_gem_frame_time=time.monotonic()-frame_age
        refresh_wallet = (self.gem_guard.refresh_async if getattr(self, '_async_wallet', False)
                          else self.gem_guard.refresh)
        refresh_wallet(screen, interval=.5 if self.user_range.minimum_gems is not None else 2.0,
                       frame_time=self._latest_gem_frame_time)
        self._latest_prize_crop = prize_crop.copy()
        self.recent_prize_crops.append(prize_crop.copy())
        self._latest_capture_completed_at = self._now()-timedelta(seconds=frame_age)
        if self._stream is not None:
            from app.stream_anchors import analyze_stream_anchors
            anchors = analyze_stream_anchors(screen,anchor_config)
        else:
            anchors = analyze_anchors(screen, anchor_config, None)
        shared = getattr(self, '_shared_fund', None)
        if shared is not None:
            reading = shared.read(self._now(), self.config.safety_frame_max_age_seconds)
            if reading.notification_grace and not self.state.continuous_session_active:
                raise FreshFrameUnavailable('Ждём свежий общий фонд для начала новой серии')
            self._shared_reading = reading
            shared.apply_cycle(self, reading, now)
            self.state.notification_veto = False
            self.state.notification_heavy = False
            self._last_production_ocr = None
            return (screen, RecognitionResult('', '', reading.value, 'shared_fund', 1.0,
                    'shared_fund', False), anchors,
                    PrefilterResult('NOT_RUN', 0, None, None, 'shared fund', {}, False, ''),
                    capture_ms, 0.0, None, False)
        started_fast = time.perf_counter()
        if self.config.fast_prefilter_enabled:
            prefilter = prefilter_range(
                prize_crop,
                self.config.digit_template_manifest_path,
                self.config.fast_prefilter_confidence_threshold,
                previous_reliable_value=self.state.last_confirmed_prize,
                reset_min_trusted_value=self.config.reset_min_trusted_value,
                max_components=self.config.fast_prefilter_max_components,
            )
            fast_template = recognize_digits_from_templates(
                prize_crop,
                self.config.digit_template_manifest_path,
                self.config.fast_ocr_confidence_threshold,
            )
        else:
            prefilter = PrefilterResult(
                "NOT_RUN",
                0.0,
                None,
                None,
                "diagnostics not run",
                {},
                False,
                "",
            )
            fast_template = FastOcrResult(
                None,
                0.0,
                "disabled",
                "",
                "diagnostics not run",
                0,
            )
        fast_ms = (time.perf_counter() - started_fast) * 1000.0

        started_ocr = time.perf_counter()
        production_result = self._ocr_pipeline.process(
            prize_crop,
            capture_id,
            control_policy=self._paddle_control_reasons,
            recovery_allowed=anchors.button_visible,
            frame_local_control=self._stream is not None,
        )
        authoritative_ocr_ms = (time.perf_counter() - started_ocr) * 1000.0
        authoritative_ocr_ran = production_result.rapid is not None
        self._last_production_ocr = production_result
        if production_result.paddle is not None and "post_burst_check" in production_result.control_reasons:
            self._post_burst_paddle_pending = False
        self.state.last_full_ocr_at = now if authoritative_ocr_ran else self.state.last_full_ocr_at
        self.state.notification_veto = (
            production_result.notification.veto
            and not production_result.recovered_after_notification
        )
        self.state.notification_heavy = production_result.notification.heavy
        self.state.notification_recovery_hits = max(
            0,
            min(2, production_result.notification.clear_streak - 1),
        )
        current = production_result.current
        rapid = production_result.rapid
        paddle = production_result.paddle
        if current is None:
            recognition = RecognitionResult(
                raw_text="",
                normalized_text="",
                value=None,
                variant_name=production_result.notification.stage,
                confidence=0.0,
                method=("notification_veto" if self.state.notification_veto else "rapid_paddle_disagreement"),
                fallback_used=False,
                fast_reason=production_result.reason,
            )
        else:
            control_detail = ""
            if paddle is not None:
                control_detail = (
                    f"; paddle={paddle.value} confidence={paddle.confidence:.6f} "
                    f"reasons={','.join(production_result.control_reasons)}"
                )
            recognition = RecognitionResult(
                raw_text=current.text,
                normalized_text=current.text,
                value=current.value,
                variant_name="full_clean_digit_roi",
                confidence=current.confidence,
                method=current.engine,
                fallback_used=False,
                fast_reason=(
                    f"{production_result.reason}; rapid_ms={rapid.latency_ms if rapid else 0.0:.3f}"
                    f"{control_detail}; prefilter_diagnostic={prefilter.reason}; template={fast_template.reason}"
                ),
            )
        self.state.last_prefilter_digit_count = prefilter.digit_count
        self.state.last_prefilter_first_digit = prefilter.first_digit
        return screen, recognition, anchors, prefilter, capture_ms, fast_ms, authoritative_ocr_ms, authoritative_ocr_ran

    def _determine_ocr_status(self, recognition: RecognitionResult, anchors: AnchorStatus) -> OcrStatus:
        if recognition.method == "notification_veto":
            return OcrStatus.OBSCURED
        if recognition.value is not None:
            return OcrStatus.VISIBLE
        if recognition.method == "windows_ocr_timeout":
            return OcrStatus.TIMEOUT
        if recognition.method == "prefilter_skip":
            return OcrStatus.SKIPPED
        return OcrStatus.ERROR

    def _seconds_since_reset(self, now: datetime) -> int | None:
        if not self.state.last_reset_at:
            return None
        return max(0, int((now - self.state.last_reset_at).total_seconds()))

    def _reset_interval_remaining(self, now: datetime) -> int | None:
        if not self.state.last_reset_at:
            return None
        elapsed = max(0, int((now - self.state.last_reset_at).total_seconds()))
        return max(0, self.config.min_reset_interval_seconds - elapsed)

    def _reset_interval_elapsed(self, now: datetime) -> bool:
        remaining = self._reset_interval_remaining(now)
        return remaining is None or remaining == 0

    def _cooldown_remaining(self, now: datetime) -> int | None:
        if not self.state.cooldown_until:
            return None
        remaining = int((self.state.cooldown_until - now).total_seconds())
        return max(0, remaining)

    def _can_start_clicking(self, value: int, anchors: AnchorStatus, now: datetime) -> bool:
        if not self.tap_decisions_enabled:
            return False
        if not self.is_target_value(value):
            return False
        if self.state.candidate_hits < self.config.stable_reads_required:
            return False
        if not anchors.event_screen_ok or not anchors.button_visible:
            return False
        if self.state.real_mode_armed and self.state.manual_reset_block_real_taps:
            return False
        if not self.state.reset_time_known:
            return False
        if self.state.cooldown_until and self.state.cooldown_until > now:
            return False
        return True

    def _anchors_allow_progress(self, anchors: AnchorStatus) -> bool:
        return anchors.event_screen_ok and anchors.button_visible

    def _reset_progress_due_to_anchors(self, phase_to_waiting: bool = True) -> None:
        if (self._stream is not None and self.config.continuous_clicking
                and self.state.continuous_session_active
                and self.state.phase == MonitorPhase.ACTIVE_CLICKING):
            now = self._now()
            if self.state.anchor_recovery_started_at is None:
                self.state.anchor_recovery_started_at = now
            if 0 <= (now-self.state.anchor_recovery_started_at).total_seconds() < .5:
                self.state.next_click_at = None
                self.state.last_status = 'Короткая пауза: ждём восстановления кнопки и экрана'
                return
        self.state.anchor_recovery_started_at = None
        self.state.continuous_session_active = False
        self._clear_candidate()
        self.state.next_click_at = None
        self.state.checking_until = None
        self.state.burst_taps_done = 0
        if phase_to_waiting and self.state.phase not in {MonitorPhase.RESET_COOLDOWN, MonitorPhase.RESET_TIME_UNKNOWN}:
            self.state.phase = MonitorPhase.WAITING
        self.state.last_status = "Якоря не подтверждены: screen_ok/button_ok обязательны, клики запрещены"

    def _update_unknown_and_cooldown(self, now: datetime) -> None:
        if not self.state.reset_time_known:
            if self.state.unknown_since is None:
                self.state.unknown_since = now
            observed = (now - self.state.unknown_since).total_seconds()
            if (observed >= self.config.reset_cooldown_seconds
                    and not self.state.manual_reset_block_real_taps
                    and not self.state.start_requires_new_reset):
                self.state.reset_time_known = True
                if self.state.phase == MonitorPhase.RESET_TIME_UNKNOWN:
                    self.state.phase = MonitorPhase.WAITING
                    self.state.last_status = "RESET_TIME_UNKNOWN завершён: можно наблюдать обычный цикл"
                self._save_persisted_state()

        if self.state.cooldown_until and now >= self.state.cooldown_until:
            self.state.cooldown_until = None
            if self.state.phase == MonitorPhase.RESET_COOLDOWN:
                self.state.phase = MonitorPhase.WAITING
                self.state.last_status = "RESET_COOLDOWN завершён"
            self._save_persisted_state()

    def _clear_candidate(self) -> None:
        self.state.candidate_value = None
        self.state.candidate_hits = 0
        self.state.candidate_capture_id = None
        self.state.candidate_at = None

    def _start_candidate(self, value: int, capture_id: str, now: datetime, status: str) -> None:
        self.state.candidate_value = value
        self.state.candidate_hits = 1
        self.state.candidate_capture_id = capture_id
        self.state.candidate_at = now
        self.state.phase = MonitorPhase.CANDIDATE
        self.state.last_status = status

    def _update_candidate(
        self,
        value: int,
        capture_id: str,
        now: datetime,
        anchors: AnchorStatus,
    ) -> None:
        if (
            self.state.notification_veto
            or self.state.ocr_status != OcrStatus.VISIBLE
            or not self._anchors_allow_progress(anchors)
        ):
            self._clear_candidate()
            if self.state.phase not in {MonitorPhase.RESET_COOLDOWN, MonitorPhase.RESET_TIME_UNKNOWN}:
                self.state.phase = MonitorPhase.WAITING
            self.state.last_status = "CANDIDATE blocked: trusted OCR safety gates are not valid"
            return

        in_range = self.is_target_value(value)
        if not in_range:
            self._clear_candidate()
            if self.state.phase not in {MonitorPhase.RESET_COOLDOWN, MonitorPhase.RESET_TIME_UNKNOWN}:
                self.state.phase = MonitorPhase.WAITING
            self.state.last_status = f"Найдено значение: {value}"
            return

        if self.state.candidate_hits == 0:
            self._start_candidate(
                value,
                capture_id,
                now,
                f"CANDIDATE: первое подтверждение {value}",
            )
            return

        if capture_id == self.state.candidate_capture_id:
            self.state.last_status = "CANDIDATE: duplicate capture ignored"
            return

        previous = self.state.candidate_value
        previous_at = self.state.candidate_at
        if previous is None or previous_at is None:
            self._start_candidate(value, capture_id, now, f"CANDIDATE: restarted at {value}")
            return

        growth = value - previous
        if growth < 0:
            self._clear_candidate()
            self.state.phase = MonitorPhase.WAITING
            self.state.last_status = f"CANDIDATE reset: backward value {previous}->{value}"
            return

        elapsed = max(0.10, (now - previous_at).total_seconds())
        allowed_growth = int(
            self.config.max_realistic_growth_per_second * elapsed
            + self.config.realistic_growth_slack
        )
        if growth <= allowed_growth:
            self.state.candidate_hits += 1
            self.state.candidate_value = value
            self.state.candidate_capture_id = capture_id
            self.state.candidate_at = now
            self.state.phase = MonitorPhase.CONFIRMED
            self.state.last_status = (
                f"CONFIRMED: подтверждений {self.state.candidate_hits}/{self.config.stable_reads_required}"
            )
            return

        self._start_candidate(
            value,
            capture_id,
            now,
            f"CANDIDATE: incompatible growth {previous}->{value}, restarted",
        )

    def _clear_reset_candidate(self) -> None:
        self.state.reset_candidate_hits = 0
        self.state.reset_candidate_value = None
        self.state.reset_last_high_at = None
        self.state.reset_first_low_at = None
        self.state.reset_first_low_value = None
        self.state.reset_first_low_capture_id = None
        self.state.reset_pre_reset_peak = None

    def _reset_reading_has_paddle_control(self, recognition: RecognitionResult) -> bool:
        return (
            recognition.method == "rapidocr_ppocrv6_onnx"
            and "confirmed by PaddleOCR" in recognition.fast_reason
            and "paddle=" in recognition.fast_reason
        )

    def _start_reset_candidate(
        self,
        value: int,
        capture_id: str,
        now: datetime,
        pre_reset_peak: int,
        previous_high_at: datetime | None,
    ) -> None:
        self.state.reset_candidate_value = value
        self.state.reset_candidate_hits = 1
        self.state.reset_last_high_at = previous_high_at
        self.state.reset_first_low_at = now
        self.state.reset_first_low_value = value
        self.state.reset_first_low_capture_id = capture_id
        self.state.reset_pre_reset_peak = pre_reset_peak

    def _update_reset_detection(
        self,
        value: int | None,
        ocr_status: OcrStatus,
        now: datetime,
        capture_id: str,
        previous_trusted_at: datetime | None,
        recognition: RecognitionResult,
        anchors: AnchorStatus,
        prefilter: PrefilterResult,
    ) -> None:
        previous_high_value = self.state.last_confirmed_prize
        previous_high_at = previous_trusted_at or self.state.last_trusted_at
        if value is None or ocr_status != OcrStatus.VISIBLE or self.state.notification_veto:
            if self.state.reset_candidate_hits > 0:
                self._clear_reset_candidate()
                self.state.last_status = "Reset candidate canceled: clean controlled OCR was lost"
            return
        if previous_high_value is None:
            self.state.last_confirmed_prize = value
            self.state.last_trusted_at = now
            return

        if self.state.reset_episode_locked:
            self.state.last_confirmed_prize = value
            self.state.last_trusted_at = now
            return

        if (
            self.state.reset_candidate_hits > 0
            and self.state.reset_first_low_at is not None
            and (now - self.state.reset_first_low_at).total_seconds()
            > self.config.reset_candidate_timeout_seconds
        ):
            self._clear_reset_candidate()
            self.state.last_status = "Reset candidate timed out"

        if not self._reset_interval_elapsed(now):
            decreased = value < previous_high_value
            self._clear_reset_candidate()
            self.state.last_confirmed_prize = value
            self.state.last_trusted_at = now
            if decreased:
                self.state.last_status = (
                    f"Reset blocked by min interval: осталось "
                    f"{self._reset_interval_remaining(now)}с"
                )
                self._save_reset_diagnostics(now, "blocked_min_interval", recognition, anchors, prefilter)
            return

        reference_peak = max(self.state.peak_since_reset or previous_high_value, previous_high_value)
        controlled = self._reset_reading_has_paddle_control(recognition)
        if self.state.reset_candidate_hits == 0:
            if value >= previous_high_value:
                self._clear_reset_candidate()
                self.state.last_confirmed_prize = value
                self.state.last_trusted_at = now
                return
            if not controlled:
                self._clear_reset_candidate()
                self.state.last_status = "Reset candidate blocked: PaddleOCR control is required"
                return
            self._start_reset_candidate(
                value,
                capture_id,
                now,
                reference_peak,
                previous_high_at,
            )
            self._save_reset_diagnostics(now, "potential", recognition, anchors, prefilter)
            return

        if capture_id == self.state.reset_first_low_capture_id:
            self.state.last_status = "Reset candidate: duplicate capture ignored"
            return
        if not controlled:
            self._clear_reset_candidate()
            self.state.last_status = "Reset candidate canceled: PaddleOCR control was lost"
            return

        first_low = self.state.reset_first_low_value
        pre_reset_peak = self.state.reset_pre_reset_peak
        first_low_at = self.state.reset_first_low_at
        if first_low is None or pre_reset_peak is None or first_low_at is None:
            self._clear_reset_candidate()
            self.state.last_status = "Reset candidate canceled: incomplete first-low evidence"
            return
        if value < first_low:
            self._start_reset_candidate(
                value,
                capture_id,
                now,
                pre_reset_peak,
                self.state.reset_last_high_at,
            )
            self.state.last_status = "Reset candidate restarted at a lower independent value"
            return
        if value >= pre_reset_peak:
            self._clear_reset_candidate()
            self.state.last_confirmed_prize = value
            self.state.last_trusted_at = now
            self.state.last_status = "False reset candidate canceled: value returned to pre-reset level"
            return

        elapsed = max(0.10, (now - first_low_at).total_seconds())
        allowed_growth = int(
            self.config.max_realistic_growth_per_second * elapsed
            + self.config.realistic_growth_slack
        )
        if value - first_low > allowed_growth:
            self._clear_reset_candidate()
            self.state.last_status = "Reset candidate canceled: incompatible low-cycle growth"
            return

        self.state.reset_candidate_value = value
        self.state.reset_candidate_hits += 1

        if self.state.reset_candidate_hits >= self.config.reset_confirm_reads_required:
            reset_event_at = first_low_at
            reset_confirmed_at = now
            self.state.last_reset_at = reset_event_at
            self.state.last_reset_confirmed_at = reset_confirmed_at
            self.state.cooldown_until = reset_event_at + timedelta(seconds=self.config.reset_cooldown_seconds)
            self.state.reset_time_known = True
            self.state.manual_reset_block_real_taps = False
            self.state.start_requires_new_reset = False
            self.state.phase = MonitorPhase.RESET_COOLDOWN
            self.state.continuous_session_active = False
            self._clear_candidate()
            self.state.burst_taps_done = 0
            self.state.next_click_at = None
            self.state.checking_until = None
            self._append_reset_history(
                pre_reset_peak,
                value,
                reset_event_at,
                reset_confirmed_at,
                self.state.reset_last_high_at,
                self.state.reset_first_low_at,
            )
            self.state.last_confirmed_prize = value
            self.state.last_trusted_at = reset_event_at
            self.state.peak_since_reset = value
            self.state.post_reset_baseline = first_low
            self.state.reset_episode_locked = True
            self.state.reset_growth_hits = 0
            self.state.reset_growth_last_value = value
            self.state.reset_growth_last_capture_id = None
            self.state.reset_growth_last_at = None
            self.state.reset_new_cycle_confirmed = False
            self.state.reset_unlock_reason = "LOCKED: waiting for 120s"
            self.state.last_status = (
                f"confirmed reset; delay={max(0.0, (reset_confirmed_at - reset_event_at).total_seconds()):.3f}s"
            )
            self._save_reset_diagnostics(
                now,
                "confirmed",
                recognition,
                anchors,
                prefilter,
                reset_event_at=reset_event_at,
                reset_confirmed_at=reset_confirmed_at,
            )
            self._clear_reset_candidate()
            self._save_persisted_state()

    def _save_trigger_diagnostics(
        self,
        screen: Image.Image,
        prize_result: RecognitionResult,
        anchors: AnchorStatus,
    ) -> Path:
        stamp = self._now().strftime("%Y%m%d_%H%M%S_%f")
        target_dir = self.config.trigger_dir / stamp
        decision_text = "\n".join(
            [
                f"value={prize_result.value}",
                f"raw={prize_result.normalized_text}",
                f"variant={prize_result.variant_name}",
                f"title_score={anchors.title_score:.3f}",
                f"screen_anchor_score={anchors.screen_anchor_score:.3f}",
                f"button_score={anchors.button_score:.3f}",
                f"gold_ratio={anchors.gold_ratio:.3f}",
                f"title_text={anchors.title_text}",
                f"button_text={anchors.button_text}",
                f"phase={self.state.phase.value}",
                f"test_mode={self.state.test_mode}",
                f"real_mode_armed={self.state.real_mode_armed}",
            ]
        )
        images = {
            "prize_crop.png": crop_rect(screen, self.config.prize_crop),
            "button_crop.png": anchors.button_crop,
        }
        full_due = self._last_full_diagnostics_at is None or (self._now()-self._last_full_diagnostics_at).total_seconds()>=5
        if self.state.real_mode_armed and (self.state.burst_taps_done==0 or full_due):
            self._last_full_diagnostics_at=self._now()
            images.update(
                {
                    "screen.png": screen,
                    "title_crop.png": crop_rect(screen, self.config.event_title_crop),
                    "pre_tap_screen.png": screen,
                }
            )
            if getattr(self, '_latest_native_screen', None) is not None:
                images['native_screen.png'] = self._latest_native_screen
        accepted = self._diagnostics_writer.submit(target_dir, images, decision_text)
        self._last_diagnostics_enqueue_accepted = accepted
        if not accepted:
            self.state.last_status = "Diagnostics queue full: PNG files skipped for this tap"
        return target_dir

    def _prepare_continuous_tap(
        self, now: datetime, trusted_value: int | None, anchors: AnchorStatus
    ) -> tuple[bool, int | None]:
        state = self.state
        frame_age = ((now - self._latest_capture_completed_at).total_seconds()
                     if self._latest_capture_completed_at is not None else float("inf"))
        if frame_age > self.config.safety_frame_max_age_seconds:
            state.next_click_at = None
            state.last_status = "Клики приостановлены: кадр экрана устарел"
            return False, None
        if not self.tap_decisions_enabled or not state.reset_time_known or (
            state.real_mode_armed and state.manual_reset_block_real_taps
        ):
            state.continuous_session_active = False
            state.next_click_at = None
            state.phase = MonitorPhase.WAITING if state.reset_time_known else MonitorPhase.RESET_TIME_UNKNOWN
            state.last_status = "Клики запрещены: наблюдение ещё не готово"
            return False, None
        if state.cooldown_until and state.cooldown_until > now:
            state.continuous_session_active = False
            state.next_click_at = None
            state.phase = MonitorPhase.RESET_COOLDOWN
            return False, None
        if (state.anchor_recovery_started_at is not None
                and (now-state.anchor_recovery_started_at).total_seconds() >= .5):
            self._reset_progress_due_to_anchors()
            return False, None
        if not state.continuous_session_active:
            if (
                trusted_value is None or not self.is_target_value(trusted_value)
                or state.candidate_hits < self.config.stable_reads_required
                or not anchors.event_screen_ok or not anchors.button_visible
                or state.notification_veto or state.ocr_status != OcrStatus.VISIBLE
            ):
                state.last_status = "Серия ожидает два подтверждения входа в диапазон"
                return False, None
            state.continuous_session_active = True
            state.anchor_recovery_started_at = None
            state.session_last_visible_at = now
            state.session_last_value = trusted_value
            state.session_reset_suspected = False

        if not anchors.button_visible or not (anchors.event_screen_ok or anchors.continuation_screen_ok):
            self._reset_progress_due_to_anchors()
            return False, None
        state.anchor_recovery_started_at = None
        if self.config.continuous_max_taps > 0 and state.burst_taps_done >= self.config.continuous_max_taps:
            self.set_real_mode(False)
            self.pause()
            self.adb.close_shell()
            state.last_status = f"Серия достигла предела {self.config.continuous_max_taps} желаний. Нажмите запуск для новой проверки."
            return False, None

        if trusted_value is not None and state.ocr_status == OcrStatus.VISIBLE and not state.notification_veto:
            if state.reset_candidate_hits or (state.session_last_value is not None and trusted_value < state.session_last_value):
                state.session_reset_suspected = True
                state.next_click_at = None
                state.last_status = "Клики остановлены: фонд упал, подтверждаем обнуление"
                return False, None
            state.session_reset_suspected = False
            state.session_last_value = trusted_value
            state.session_last_visible_at = now
        elif state.session_reset_suspected:
            state.next_click_at = None
            state.last_status = "Клики остановлены: ждём подтверждение обнуления"
            return False, None
        elif state.notification_veto or state.ocr_status == OcrStatus.OBSCURED:
            elapsed = ((now - state.session_last_visible_at).total_seconds()
                       if state.session_last_visible_at is not None else float("inf"))
            if elapsed > self.config.continuous_visibility_grace_seconds:
                state.next_click_at = None
                state.last_status = "Цифры долго закрыты: клики приостановлены до восстановления наблюдения"
                return False, None
        else:
            state.next_click_at = None
            state.last_status = "Клики приостановлены: ожидаем достоверное чтение фонда"
            return False, None
        return True, state.session_last_value

    def _handle_active_clicking(
        self,
        now: datetime,
        screen: Image.Image,
        recognition: RecognitionResult,
        trusted_value: int | None,
        anchors: AnchorStatus,
        tap_events: list[str],
    ) -> tuple[bool, bool, Path | None]:
        clicked = False
        would_tap = False
        diagnostics_dir: Path | None = None

        if self._tap_cancel.is_set():
            return clicked, would_tap, diagnostics_dir
        shared = getattr(self, '_shared_fund', None)
        if shared is not None and not shared.permits_current(self):
            self.state.next_click_at = None
            self.state.last_status = 'Клики ждут: нет свежего разрешения общего фонда'
            return clicked, would_tap, diagnostics_dir
        if self.state.phase != MonitorPhase.ACTIVE_CLICKING:
            return clicked, would_tap, diagnostics_dir
        floor = self.user_range.minimum_gems
        if self.state.real_mode_armed and floor is not None:
            if getattr(self, '_async_wallet', False):
                permitted, reason = self.gem_guard.permits_cached(floor)
            else:
                permitted, reason = self.gem_guard.permits(screen, floor, frame_time=getattr(self,'_latest_gem_frame_time',None))
            if not permitted:
                if reason != 'floor':
                    self.state.next_click_at = None
                    self.state.last_status = "Клики ждут: проверяем баланс самоцветов. Режим «С кликами» сохранён"
                    return False, False, None
                self.set_real_mode(False)
                self.resume()
                self.state.last_status = "С кликами выключено: достигнут сохранённый остаток самоцветов"
                tap_events.append(self.state.last_status)
                return False, False, None
        continuous = self.config.continuous_clicking
        if continuous:
            permitted, trusted_value = self._prepare_continuous_tap(self._now(), trusted_value, anchors)
            if not permitted:
                return clicked, would_tap, diagnostics_dir
        if not continuous and (self.state.notification_veto or self.state.ocr_status == OcrStatus.OBSCURED):
            self.state.phase = MonitorPhase.CHECKING_AFTER_BURST
            self.state.next_click_at = None
            self.state.checking_until = None
            self.state.last_status = "CHECKING_AFTER_BURST: notification veto, tap series stopped"
            return clicked, would_tap, diagnostics_dir
        if not continuous and (self.state.ocr_status != OcrStatus.VISIBLE or trusted_value is None):
            self._clear_candidate()
            self.state.next_click_at = None
            self.state.checking_until = None
            self.state.burst_taps_done = 0
            self.state.phase = MonitorPhase.WAITING
            self.state.last_status = "ACTIVE_CLICKING stopped: current trusted value is unavailable"
            return clicked, would_tap, diagnostics_dir
        if not continuous and not self.is_target_value(trusted_value):
            self._clear_candidate()
            self.state.next_click_at = None
            self.state.checking_until = None
            self.state.burst_taps_done = 0
            self.state.phase = MonitorPhase.WAITING
            self.state.last_status = (
                f"ACTIVE_CLICKING stopped: current value {trusted_value} is outside target range"
            )
            return clicked, would_tap, diagnostics_dir
        if not anchors.button_visible or not (anchors.event_screen_ok or (continuous and anchors.continuation_screen_ok)):
            self._reset_progress_due_to_anchors()
            self.state.last_status = "ACTIVE_CLICKING stopped: safety anchors are not valid"
            return clicked, would_tap, diagnostics_dir
        if not self.tap_decisions_enabled:
            self._clear_candidate()
            self.state.next_click_at = None
            self.state.checking_until = None
            self.state.burst_taps_done = 0
            self.state.phase = MonitorPhase.WAITING
            self.state.last_status = "ACTIVE_CLICKING stopped: tap decisions are disabled"
            return clicked, would_tap, diagnostics_dir
        if not self.state.reset_time_known:
            self._clear_candidate()
            self.state.next_click_at = None
            self.state.checking_until = None
            self.state.burst_taps_done = 0
            self.state.phase = MonitorPhase.RESET_TIME_UNKNOWN
            self.state.last_status = "ACTIVE_CLICKING stopped: reset time is unknown"
            return clicked, would_tap, diagnostics_dir
        if self.state.cooldown_until and self.state.cooldown_until > now:
            self._clear_candidate()
            self.state.next_click_at = None
            self.state.checking_until = None
            self.state.burst_taps_done = 0
            self.state.phase = MonitorPhase.RESET_COOLDOWN
            self.state.last_status = "ACTIVE_CLICKING stopped: reset cooldown is active"
            return clicked, would_tap, diagnostics_dir
        if self.state.real_mode_armed and self.state.manual_reset_block_real_taps:
            self._clear_candidate()
            self.state.next_click_at = None
            self.state.checking_until = None
            self.state.burst_taps_done = 0
            self.state.phase = MonitorPhase.RESET_TIME_UNKNOWN
            self.state.last_status = "ACTIVE_CLICKING stopped: real taps are blocked after manual reset"
            return clicked, would_tap, diagnostics_dir

        actual_now = self._now()
        interval = (1.0 / self.user_range.clicks_per_second if continuous
                    else self.config.click_interval_seconds)
        frame_age = (
            (actual_now - self._latest_capture_completed_at).total_seconds()
            if self._latest_capture_completed_at is not None
            else float("inf")
        )
        if frame_age > self.config.safety_frame_max_age_seconds:
            self.state.phase = MonitorPhase.CHECKING_AFTER_BURST
            self.state.next_click_at = None
            self.state.checking_until = None
            self.state.last_status = f"Tap blocked: safety frame is {frame_age:.3f}s old"
            return clicked, would_tap, diagnostics_dir

        if self.state.next_click_at is None:
            self.state.next_click_at = actual_now
        if actual_now < self.state.next_click_at:
            return clicked, would_tap, diagnostics_dir
        if (
            self.state.last_tap_sent_at is not None
            and (actual_now - self.state.last_tap_sent_at).total_seconds() < interval
        ):
            self.state.next_click_at = self.state.last_tap_sent_at + timedelta(
                seconds=interval
            )
            return clicked, would_tap, diagnostics_dir

        diagnostics_dir = self._save_trigger_diagnostics(screen, recognition, anchors)
        if not getattr(self, "_last_diagnostics_enqueue_accepted", True):
            tap_events.append(
                f"{actual_now.strftime('%H:%M:%S.%f')[:-3]} WARNING diagnostics queue full"
            )
        if self._tap_cancel.is_set():
            return False, False, None
        if self.state.real_mode_armed:
            if self.config.session_real_tap_limit and self.state.real_taps >= self.config.session_real_tap_limit:
                self.set_real_mode(False)
                self.pause()
                self.state.last_status = "Лимит настоящих нажатий достигнут"
                return False, False, diagnostics_dir
            audit_path = self.config.runtime_dir / "tap_audit.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit = dict(timestamp=actual_now.astimezone().isoformat(), event="tap_attempt",
                         number=self.state.real_taps + 1, value=trusted_value,
                         range=self.target_range_for_mode(), screen_ok=anchors.event_screen_ok,
                         button_ok=anchors.button_visible, frame_age_seconds=frame_age,
                         notification_veto=self.state.notification_veto,
                         continuation_screen_ok=anchors.continuation_screen_ok,
                         last_visible_at=self.state.session_last_visible_at.isoformat() if self.state.session_last_visible_at else None,
                         decision="notification_grace" if self.state.notification_veto else "visible_number",
                         x=self._native_point(self.config.tap_point.x, self.config.tap_point.y)[0],
                         y=self._native_point(self.config.tap_point.x, self.config.tap_point.y)[1])
            with audit_path.open("a", encoding="utf-8") as audit_file:
                audit_file.write(json.dumps(audit) + "\n")
            try:
                if (getattr(self, '_async_wallet', False) and floor is not None
                        and not self.gem_guard.permits_cached(floor)[0]):
                    self.state.next_click_at = None
                    self.state.last_status = 'Клики ждут свежую проверку баланса'
                    return False, False, None
                if (self._tap_cancel.is_set() or self.state.phase != MonitorPhase.ACTIVE_CLICKING
                        or floor != self.user_range.minimum_gems
                        or (shared is not None and not shared.permits_current(self))):
                    self.state.last_status = "Нажатие отменено пользователем"
                    return False, False, None
                if self._stream is not None:
                    point = self._native_point(self.config.tap_point.x, self.config.tap_point.y)
                    if self._screen_geometry is None:
                        self._stream.tap(*point)
                    else:
                        self._stream.tap(*point, expected_size=(self._screen_geometry.width,self._screen_geometry.height))
                else:
                    self.adb.tap_persistent(*self._native_point(self.config.tap_point.x, self.config.tap_point.y))
            except FreshFrameUnavailable:
                self.state.next_click_at = None
                self.state.last_status = "Нажатия приостановлены: ждём свежий видеокадр"
                return False, False, None
            except Exception:
                self.set_real_mode(False)
                self.pause()
                self.adb.close_shell()
                self.state.last_status = "Ошибка ADB: режим выключен, повтор команды запрещён"
                raise
            self.state.real_taps += 1
            if floor is not None:
                self.gem_guard.reserve_sent_tap()
            audit["event"] = "tap_sent"
            with audit_path.open("a", encoding="utf-8") as audit_file:
                audit_file.write(json.dumps(audit) + "\n")
            clicked = True
            tap_events.append(f"{actual_now.strftime('%H:%M:%S.%f')[:-3]} REAL adb tap")
        else:
            self.state.virtual_taps += 1
            would_tap = True
            tap_events.append(f"{actual_now.strftime('%H:%M:%S.%f')[:-3]} virtual tap")
        self.state.last_tap_sent_at = actual_now
        self.state.burst_taps_done += 1
        self.state.total_taps += 1
        self.state.next_click_at = actual_now + timedelta(seconds=interval)
        self.state.last_status = (
            f"ACTIVE_CLICKING: tap {self.state.burst_taps_done}/{(self.config.continuous_max_taps or 'до reset') if continuous else self.config.burst_size}, "
            f"total {self.state.total_taps}"
        )
        if continuous and self.state.notification_veto:
            self.state.last_status += "; краткое уведомление, серия продолжается"
        if not continuous and self.state.burst_taps_done >= self.config.burst_size:
            self.state.phase = MonitorPhase.CHECKING_AFTER_BURST
            self.state.checking_until = actual_now + timedelta(seconds=self.config.provisional_check_pause_seconds)
            self._post_burst_paddle_pending = True
            self.state.last_status = "CHECKING_AFTER_BURST: waiting for clean frames after burst"

        if clicked and self.config.session_real_tap_limit and self.state.real_taps >= self.config.session_real_tap_limit:
            self.set_real_mode(False)
            self.pause()
            self.adb.close_shell()
            self.state.last_status = "Лимит настоящих нажатий достигнут. Монитор на паузе."

        return clicked, would_tap, diagnostics_dir

    def _format_reset_time(self) -> str:
        if not self.state.last_reset_at:
            return "—"
        return self.state.last_reset_at.strftime("%H:%M:%S")

    def _format_reset_confirmed_time(self) -> str:
        if not self.state.last_reset_confirmed_at:
            return "—"
        return self.state.last_reset_confirmed_at.strftime("%H:%M:%S")

    def poll_once(self) -> PollSnapshot:
        now = self._now()
        capture_id = now.astimezone(self._local_zone()).strftime("%Y%m%d_%H%M%S_%f")
        timestamp = self.timestamp()
        clicked = False
        would_tap = False
        diagnostics_dir: Path | None = None
        tap_events: list[str] = []
        reset_average_label, reset_min_label, reset_max_label = self._history_stats()

        self._update_unknown_and_cooldown(now)

        # A rejected anchor/OCR frame is not a stopped video stream. Retain the
        # reset baseline during continuous capture, but never use it for taps.
        self._expire_interrupted_observation(now)
        previous_trusted_at = self.state.last_trusted_at
        screen, recognition, anchors, prefilter, capture_ms, fast_observation_ms, authoritative_ocr_ms, authoritative_ocr_ran = self._capture_context(now)
        self._last_observation_at = now
        popup = self._current_popup
        popup_ready = self._popup_dismissal.observe(popup, self._stream_sequence)
        if popup is not None:
            self._clear_candidate()
            self.state.continuous_session_active = False
            self.state.next_click_at = None
            if self.state.phase in {MonitorPhase.CANDIDATE, MonitorPhase.CONFIRMED,
                                    MonitorPhase.ACTIVE_CLICKING, MonitorPhase.CHECKING_AFTER_BURST}:
                self.state.phase = MonitorPhase.WAITING
            self.state.last_status = "Мешающее окно: желания остановлены"
            if (popup_ready and self._stream is not None and self.tap_decisions_enabled
                    and not self._tap_cancel.is_set()
                    and self.state.phase not in {MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP}):
                # Recheck a fresh independent frame immediately before normal Android input.
                safety = self._stream.frame()
                from app.screen_geometry import ScreenGeometry
                safety_geometry = ScreenGeometry(*safety.image.size)
                if (safety_geometry == (getattr(self, '_screen_geometry', None) or ScreenGeometry(1080,1080))
                        and self._popup_dismissal.detect(safety_geometry.normalize(safety.image)) == popup
                        and not self._tap_cancel.is_set()):
                    self._popup_dismissal.reserve_attempt()
                    folder = self.config.screenshot_path.parent / "popup_dismissals"
                    folder.mkdir(parents=True, exist_ok=True)
                    safety.image.save(folder / f"{capture_id}_{popup.kind}.png")
                    if not self._tap_cancel.is_set():
                        if getattr(self, '_screen_geometry', None) is None:
                            self._stream.tap(*popup.point)
                        else:
                            self._stream.tap(*safety_geometry.to_native(*popup.point), expected_size=safety.image.size)
                        event = f"{timestamp} popup_close kind={popup.kind} point={popup.point}"
                        with (folder / "events.jsonl").open("a", encoding="utf-8") as log:
                            log.write(json.dumps({"timestamp": timestamp, "kind": popup.kind,
                                                  "point": popup.point, "wish_tap": False}) + "\n")
                        tap_events.append(event)
                        self.state.last_status = "Закрываем мешающее окно; ждём экран желаний"
        prize_crop = crop_rect(screen, self.config.prize_crop)
        self.state.ocr_status = self._determine_ocr_status(recognition, anchors)
        self.state.raw_ocr_value = recognition.value
        trusted_value, trust_reason = (
            (recognition.value, 'shared confirmed fund') if recognition.method == 'shared_fund'
            else self._resolve_trusted_value(recognition.value, now)
            if self.state.ocr_status == OcrStatus.VISIBLE
            else (None, "OCR not visible")
        )
        self.state.trusted_value = trusted_value
        if trusted_value is not None:
            self.state.last_value = trusted_value
        self.state.last_trust_reason = trust_reason
        from app.observation_activity import ObservationActivity
        if not hasattr(self, '_observation_activity'):
            self._observation_activity = ObservationActivity()
        activity_balance = getattr(getattr(self, 'gem_guard', None), 'balance', None)
        self.state.fast_observation_active = self._observation_activity.observe(
            screen_ok=anchors.button_visible and (anchors.event_screen_ok or anchors.continuation_screen_ok),
            notification=self.state.notification_veto,
            balance=activity_balance,
            reset_at=self.state.last_reset_confirmed_at,
            paused=self.state.phase in {MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP},
        )
        in_range = trusted_value is not None and self.is_target_value(trusted_value)
        anchors_ok = self._anchors_allow_progress(anchors)
        continuation_ok = (
            self.config.continuous_clicking and self.state.continuous_session_active
            and anchors.continuation_screen_ok and anchors.button_visible
        )
        self._append_observation(now, recognition, anchors, prefilter)

        if (
            self.state.reset_candidate_hits > 0
            and (
                self.state.notification_veto
                or self.state.ocr_status != OcrStatus.VISIBLE
                or trusted_value is None
            )
        ):
            self._clear_reset_candidate()
            self.state.last_status = "Reset candidate canceled: clean controlled OCR was lost"

        if (
            self.state.phase not in {MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP}
            and recognition.method != 'shared_fund'
            and (anchors_ok or continuation_ok)
            and self.state.ocr_status == OcrStatus.VISIBLE
            and trusted_value is not None
        ):
            self._update_peak_tracking(trusted_value, recognition)
            self._update_reset_episode_lock(trusted_value, now, capture_id)
            self._update_reset_detection(
                trusted_value,
                self.state.ocr_status,
                now,
                capture_id,
                previous_trusted_at=previous_trusted_at,
                recognition=recognition,
                anchors=anchors,
                prefilter=prefilter,
            )

        if self.state.last_reset_confirmed_at != self._observation_activity.reset_at:
            self.state.fast_observation_active = self._observation_activity.observe(
                screen_ok=True, notification=self.state.notification_veto,
                balance=activity_balance, reset_at=self.state.last_reset_confirmed_at,
            )

        if (
            self.state.phase not in {MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP}
            and self.state.ocr_status == OcrStatus.VISIBLE
            and recognition.value is not None
            and trusted_value is None
        ):
            diagnostics_dir = self._save_outlier_diagnostics(screen, prize_crop, recognition, now, trust_reason)

        if not (anchors_ok or continuation_ok) and self.state.phase in {
            MonitorPhase.WAITING,
            MonitorPhase.CANDIDATE,
            MonitorPhase.CONFIRMED,
            MonitorPhase.ACTIVE_CLICKING,
            MonitorPhase.CHECKING_AFTER_BURST,
        }:
            self._reset_progress_due_to_anchors()

        if self.state.notification_veto and self.state.phase in {
            MonitorPhase.WAITING,
            MonitorPhase.CANDIDATE,
            MonitorPhase.CONFIRMED,
        }:
            self._clear_candidate()
            self.state.phase = MonitorPhase.WAITING

        if self.state.phase == MonitorPhase.CHECKING_AFTER_BURST:
            if not anchors_ok:
                self.state.last_status = "Якоря потеряны во время CHECKING_AFTER_BURST: возобновление кликов запрещено"
            elif self.state.checking_until and now < self.state.checking_until:
                self.state.last_status = "CHECKING_AFTER_BURST: пауза перед OCR-проверкой"
            elif self.state.ocr_status == OcrStatus.OBSCURED:
                self.state.last_status = "CHECKING_AFTER_BURST: число ещё закрыто уведомлением"
            elif self.state.ocr_status == OcrStatus.TIMEOUT:
                self.state.last_status = "CHECKING_AFTER_BURST: Windows OCR timeout, ждём следующий кадр"
            else:
                self.state.burst_taps_done = 0
                self.state.next_click_at = None
                self.state.checking_until = None
                self.state.phase = MonitorPhase.WAITING
                self.state.last_status = "CHECKING_AFTER_BURST завершён"

        elif self.state.phase == MonitorPhase.ACTIVE_CLICKING:
            if not (anchors_ok or continuation_ok):
                self._reset_progress_due_to_anchors()
            else:
                clicked, would_tap, diagnostics_dir = self._handle_active_clicking(
                    now, screen, recognition, trusted_value, anchors, tap_events
                )

        elif self.state.phase == MonitorPhase.RESET_COOLDOWN:
            self.state.last_status = "RESET_COOLDOWN: клики запрещены"

        elif self.state.phase == MonitorPhase.RESET_TIME_UNKNOWN:
            if self.state.start_requires_new_reset:
                self.state.last_status = 'Последнее обнуление устарело. Ждём новое подтверждённое обнуление.'
            elif self.state.manual_reset_block_real_taps:
                self.state.last_status = "RESET_TIME_UNKNOWN: после ручного сброса ждём новое достоверное обнуление"
            else:
                self.state.last_status = "RESET_TIME_UNKNOWN: ждём 120 секунд безопасного наблюдения"

        elif self.state.phase in {MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP}:
            pass

        else:
            if not anchors_ok:
                self._reset_progress_due_to_anchors()
            elif self.state.ocr_status == OcrStatus.VISIBLE and trusted_value is not None:
                if self.state.phase != MonitorPhase.RESET_COOLDOWN:
                    candidate_id = (f'shared-{self._shared_reading.sequence}'
                                    if recognition.method == 'shared_fund' else capture_id)
                    self._update_candidate(trusted_value, candidate_id, now, anchors)
                    if self._can_start_clicking(trusted_value, anchors, now):
                        self.state.phase = MonitorPhase.ACTIVE_CLICKING
                        self.state.burst_taps_done = 0
                        self.state.next_click_at = now
                        self.state.last_status = "ACTIVE_CLICKING: старт тестовой серии"
                        clicked, would_tap, diagnostics_dir = self._handle_active_clicking(
                            now,
                            screen,
                            recognition,
                            trusted_value,
                            anchors,
                            tap_events,
                        )
            elif self.state.ocr_status == OcrStatus.VISIBLE and recognition.value is not None:
                self._clear_candidate()
                self.state.last_status = f"OCR outlier rejected: {trust_reason}"
            elif self.state.ocr_status == OcrStatus.OBSCURED:
                self.state.last_status = "Фонд временно закрыт уведомлением. Ожидание чистого кадра."
            elif self.state.ocr_status == OcrStatus.TIMEOUT:
                self._clear_candidate()
                self.state.last_status = "Windows OCR timeout"
            else:
                self._clear_candidate()
                self.state.last_status = "Ошибка распознавания"

        if self.state.ocr_status == OcrStatus.SKIPPED and self.state.phase in {MonitorPhase.WAITING, MonitorPhase.CANDIDATE, MonitorPhase.CONFIRMED}:
            self._clear_candidate()
            self.state.last_status = f"Prefilter: {prefilter.status} ({prefilter.reason})"

        if (
            self.state.ocr_status == OcrStatus.OBSCURED
            and self.state.phase not in {MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP}
            and not (self.config.continuous_clicking and self.state.phase == MonitorPhase.ACTIVE_CLICKING)
        ):
            self.state.last_status = "Фонд временно закрыт уведомлением. Ожидание чистого кадра."
        elif (
            recognition.method == "rapid_paddle_disagreement"
            and self.state.phase not in {MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP}
            and not (self.config.continuous_clicking and self.state.phase == MonitorPhase.ACTIVE_CLICKING)
        ):
            self.state.last_status = "RapidOCR и PaddleOCR расходятся. Ожидание следующего чистого кадра."

        self._save_persisted_state()

        return PollSnapshot(
            timestamp=timestamp,
            value=self.state.last_value,
            raw_value=recognition.value,
            trusted_value=trusted_value,
            status=self.state.last_status,
            phase=self.state.phase,
            ocr_status=self.state.ocr_status,
            confirmation_hits=self.state.candidate_hits,
            in_range=in_range,
            event_screen_ok=anchors.event_screen_ok,
            button_visible=anchors.button_visible,
            title_score=anchors.title_score,
            screen_anchor_score=anchors.screen_anchor_score,
            button_score=anchors.button_score,
            button_gold_ratio=anchors.gold_ratio,
            title_text=anchors.title_text,
            button_text=anchors.button_text,
            prefilter_status=prefilter.status,
            prefilter_confidence=prefilter.confidence,
            prefilter_digit_count=prefilter.digit_count,
            prefilter_first_digit=prefilter.first_digit,
            recognition=recognition,
            clicked=clicked,
            would_tap=would_tap,
            diagnostics_dir=str(diagnostics_dir) if diagnostics_dir else None,
            last_reset_at=self._format_reset_time(),
            last_reset_confirmed_at=self._format_reset_confirmed_time(),
            seconds_since_reset=self._seconds_since_reset(now),
            cooldown_remaining=self._cooldown_remaining(now),
            active_burst_taps=self.state.burst_taps_done,
            total_taps=self.state.total_taps,
            reset_history_rows=self._history_rows(),
            reset_average_label=reset_average_label,
            reset_min_label=reset_min_label,
            reset_max_label=reset_max_label,
            reset_since_history_label=self._history_since_reset_label(now),
            since_reset_label=self._format_since_reset_label(now),
            cooldown_label=(
                self._format_duration(self._cooldown_remaining(now))
                if self._cooldown_remaining(now) is not None
                else "—"
            ),
            mode_banner=self.mode_banner(),
            target_range_label=self.target_range_label(),
            editable_test_range_label=self.editable_test_range_label(),
            real_taps_label=self.real_taps_label(),
            tap_events=tap_events,
            capture_ms=capture_ms,
            fast_observation_ms=fast_observation_ms,
            authoritative_ocr_ms=authoritative_ocr_ms,
            authoritative_ocr_ran=authoritative_ocr_ran,
            notification_veto=self.state.notification_veto,
            notification_heavy=self.state.notification_heavy,
            notification_recovery_hits=self.state.notification_recovery_hits,
            paddle_control_ran=(
                self._last_production_ocr is not None
                and self._last_production_ocr.paddle is not None
            ),
            continuation_screen_ok=anchors.continuation_screen_ok,
        )

    @staticmethod
    def timestamp() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def close(self) -> None:
        self.set_real_mode(False)
        self.adb.close_shell()
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        self._diagnostics_writer.close(timeout=None)
