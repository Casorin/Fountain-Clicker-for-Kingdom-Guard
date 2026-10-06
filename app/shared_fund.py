"""One fresh prize observation for a group, never shared account safety."""
import threading
from dataclasses import dataclass

from app.stream_transport import FreshFrameUnavailable


CYCLE_FIELDS = ('last_reset_at', 'last_reset_confirmed_at', 'cooldown_until',
                'reset_time_known', 'unknown_since', 'manual_reset_block_real_taps',
                'reset_episode_token', 'last_confirmed_prize', 'last_trusted_at',
                'peak_since_reset', 'reset_candidate_hits')


@dataclass(frozen=True)
class FundReading:
    value: int
    captured_at: object
    sequence: int
    cycle: dict
    history: tuple
    notification_grace: bool = False


class SharedFund:
    def __init__(self, source):
        self.source = source
        self.lock = threading.Lock()
        self.reading = None
        self.sequence = 0

    def invalidate(self):
        with self.lock:
            self.reading = None

    def publish(self, monitor, snapshot):
        from app.monitor import MonitorPhase
        state = monitor.state
        now = monitor._now()
        grace = (snapshot.notification_veto and snapshot.trusted_value is None
                 and getattr(monitor.config, 'continuous_clicking', False)
                 and state.phase == MonitorPhase.ACTIVE_CLICKING
                 and state.continuous_session_active and not state.session_reset_suspected
                 and state.session_last_value is not None and state.session_last_visible_at is not None
                 and snapshot.button_visible
                 and 0 <= (now-state.session_last_visible_at).total_seconds()
                 <= monitor.config.continuous_visibility_grace_seconds)
        value = state.session_last_value if grace else snapshot.trusted_value
        with self.lock:
            self.sequence += 1
            if (not self.source.active.is_set() or monitor.state.phase in {MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP}
                    or value is None
                    or not (snapshot.event_screen_ok or getattr(snapshot, 'continuation_screen_ok', False))
                    or (snapshot.notification_veto and not grace) or monitor.state.reset_candidate_hits):
                self.reading = None
                return
            self.reading = FundReading(
                value, monitor._latest_capture_completed_at,
                self.sequence, {key: getattr(monitor.state, key) for key in CYCLE_FIELDS},
                tuple(monitor.reset_history), grace)

    def read(self, now, max_age):
        with self.lock:
            reading = self.reading
        if (not self.source.active.is_set() or reading is None
                or reading.captured_at is None
                or not 0 <= (now-reading.captured_at).total_seconds() <= max_age):
            raise FreshFrameUnavailable('Ждём свежий общий фонд из первого выбранного окна')
        return reading

    def apply_cycle(self, monitor, reading, now):
        state = monitor.state
        changed = state.last_reset_at != reading.cycle['last_reset_at']
        for key, value in reading.cycle.items():
            setattr(state, key, value)
        monitor.reset_history = list(reading.history)
        if changed or not state.reset_time_known or (state.cooldown_until and state.cooldown_until > now):
            from app.monitor import MonitorPhase
            monitor._clear_candidate()
            state.continuous_session_active = False
            state.next_click_at = None
            state.phase = (MonitorPhase.RESET_TIME_UNKNOWN if not state.reset_time_known
                           else MonitorPhase.RESET_COOLDOWN if state.cooldown_until and state.cooldown_until > now
                           else MonitorPhase.WAITING)

    def permits_current(self, monitor):
        used = getattr(monitor, '_shared_reading', None)
        try:
            fresh = self.read(monitor._now(), monitor.config.safety_frame_max_age_seconds)
        except FreshFrameUnavailable:
            return False
        return (used is not None and fresh.value >= used.value
                and (not fresh.notification_grace or monitor.state.continuous_session_active)
                and fresh.cycle['last_reset_at'] == used.cycle['last_reset_at']
                and fresh.cycle['reset_time_known']
                and not fresh.cycle['manual_reset_block_real_taps']
                and not fresh.cycle['reset_candidate_hits']
                and (not fresh.cycle['cooldown_until'] or fresh.cycle['cooldown_until'] <= monitor._now()))
