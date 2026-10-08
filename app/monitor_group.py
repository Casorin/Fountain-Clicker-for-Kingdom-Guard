"""Independent monitor workers; a failure in one device never selects another."""
import queue
import threading
import time

from PIL import Image
from app.monitor import MonitorPhase
from app.stream_transport import FreshFrameUnavailable


class MonitorSession:
    def __init__(self, window, monitor, publish):
        self.window, self.monitor, self.publish = window, monitor, publish
        self.active = threading.Event()
        self.stopping = threading.Event()
        self.thread = None
        self.requested_real = False
        self.mode_version = 0
        self.applied_mode_version = -1
        self.prepared = False
        self.settings = None
        self.settings_version = 0
        self.applied_settings_version = 0
        self.reset_requested = threading.Event()
        self.shared_fund = None
        self.fund_source = False
        self.last_error = None
        self.frame_waits = 0
        self.fund_waits = 0
        self.last_wait_reason = None
        self.poll_ms = None
        self.activity_peers = ()

    def reset_cycle(self):
        self.request_mode(False)
        self.reset_requested.set()
        if self.thread is None or not self.thread.is_alive():
            self._apply_reset()

    def _apply_reset(self):
        self.reset_requested.clear()
        self.monitor.reset_lock()
        self.monitor.state.reset_time_known = False
        self.monitor.state.manual_reset_block_real_taps = True
        self.monitor.state.unknown_since = self.monitor._now()
        self.monitor.state.phase = MonitorPhase.RESET_TIME_UNKNOWN
        self.monitor.state.last_status = 'Ждём новое обнуление. История сохранена, клики выключены.'
        self.monitor._save_persisted_state()
        self.publish(self.window.uuid, 'reset', self.monitor.state.last_status)

    def start(self):
        if self.stopping.is_set() and self.thread is not None and self.thread.is_alive():
            return
        if self.active.is_set():
            return
        # A paused worker may already have consumed the mode version. A new
        # start must reapply the current mode and resume, never inherit PAUSED.
        self.mode_version += 1
        self.stopping.clear()
        self.active.set()
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run, name=f'kgpm-window-{self.window.uuid}', daemon=True)
            self.thread.start()

    def pause(self):
        self.active.clear()
        self.monitor._tap_cancel.set()
        # Disarm current inputs, but retain the user's mode for F8 resume.
        self.mode_version += 1
        self.monitor.set_real_mode(False)
        self.monitor.pause()

    def request_mode(self, enabled):
        if not enabled:
            self.monitor._tap_cancel.set()
            self.monitor.set_real_mode(False)
        self.requested_real = bool(enabled)
        self.mode_version += 1

    def stop(self):
        self.request_mode(False)
        self.pause()
        self.stopping.set()

    def run(self):
        try:
            while not self.stopping.is_set():
                if self.reset_requested.is_set():
                    self._apply_reset()
                if not self.active.wait(.05):
                    continue
                try:
                    if self.monitor.config.stream_transport_enabled and self.monitor._stream is None:
                        self.publish(self.window.uuid, 'status', 'Подключаем окно…')
                        ok, message = self.monitor.connect()
                        if not ok:
                            raise RuntimeError(message)
                    if not self.prepared:
                        self.publish(self.window.uuid, 'status', 'Готовим распознавание…')
                        pipeline = getattr(self.monitor, '_ocr_pipeline', None)
                        if pipeline is not None and (self.shared_fund is None or self.fund_source):
                            rect = self.monitor.config.prize_crop
                            pipeline.engines.warm_up(Image.new('RGB', (rect.width, rect.height), '#505050'))
                        self.prepared = True
                    if not self.active.is_set() or self.stopping.is_set():
                        continue
                    if self.settings_version != self.applied_settings_version:
                        self.monitor.user_range = self.settings
                        self.monitor._clear_candidate()
                        self.monitor.state.continuous_session_active = False
                        self.monitor.state.next_click_at = None
                        if self.monitor.state.phase in {MonitorPhase.ACTIVE_CLICKING, MonitorPhase.CANDIDATE,
                                                       MonitorPhase.CONFIRMED, MonitorPhase.CHECKING_AFTER_BURST}:
                            self.monitor.state.phase = MonitorPhase.WAITING
                        self.applied_settings_version = self.settings_version
                    if self.mode_version != self.applied_mode_version:
                        version, enabled = self.mode_version, self.requested_real
                        ok, message = self.monitor.set_real_mode(enabled)
                        if version != self.mode_version:
                            self.monitor.set_real_mode(False)
                            continue
                        self.applied_mode_version = version
                        if not ok:
                            self.requested_real = False
                            raise RuntimeError(message)
                        self.monitor.resume()
                    if not self.active.is_set() or self.stopping.is_set():
                        self.monitor._tap_cancel.set()
                        continue
                    if self.mode_version != self.applied_mode_version:
                        self.monitor._tap_cancel.set()
                        continue
                    was_armed = self.monitor.state.real_mode_armed
                    poll_started = time.perf_counter()
                    snapshot = self.monitor.poll_once()
                    self.poll_ms = (time.perf_counter()-poll_started)*1000
                    self.last_error = None
                    self.last_wait_reason = None
                    if self.fund_source:
                        self.shared_fund.publish(self.monitor, snapshot)
                    if (was_armed and not self.monitor.state.real_mode_armed
                            and self.active.is_set() and self.mode_version == self.applied_mode_version):
                        # A wallet/safety stop must never automatically re-arm this device.
                        self.requested_real = False
                    if self.active.is_set() and not self.stopping.is_set() and not self.reset_requested.is_set():
                        self.publish(self.window.uuid, 'snapshot', snapshot)
                    fast = getattr(self.monitor.state, 'fast_observation_active', False)
                    if self.fund_source:
                        fast = fast or any(s.active.is_set() and getattr(s.monitor.state, 'fast_observation_active', False)
                                           for s in self.activity_peers)
                    delay = .001 if self.monitor.state.phase == MonitorPhase.ACTIVE_CLICKING or fast else self.monitor.config.poll_interval_ms/1000
                    self.stopping.wait(delay)
                except FreshFrameUnavailable as exc:
                    if self.fund_source:
                        self.shared_fund.invalidate()
                    self.monitor.state.next_click_at = None
                    fund_wait = 'общий фонд' in str(exc)
                    if fund_wait:
                        self.fund_waits += 1
                    else:
                        self.frame_waits += 1
                    self.last_wait_reason = 'общий фонд' if fund_wait else 'видеокадр'
                    self.publish(self.window.uuid, 'status', 'Ждём свежий общий фонд' if fund_wait else 'Ждём свежий видеокадр')
                    self.stopping.wait(.1)
                except Exception as exc:
                    if self.fund_source:
                        self.shared_fund.invalidate()
                    self.pause()
                    self.request_mode(False)
                    self.last_error = str(exc)
                    self.monitor.state.last_status = 'Окно остановлено: ' + str(exc)
                    self.publish(self.window.uuid, 'error', str(exc))
        finally:
            self.monitor.close()


class MonitorGroup:
    def __init__(self, entries):
        entries = list(entries)
        if len({window.uuid for window, _monitor in entries}) != len(entries):
            raise ValueError('An MEmu device must not have two monitor workers')
        self.events = queue.Queue(maxsize=128)
        self.sessions = {window.uuid: MonitorSession(window, monitor, self.publish) for window, monitor in entries}
        if len(entries) > 1 and all(hasattr(m, '_capture_context') for _, m in entries):
            from app.shared_fund import SharedFund
            source = next(iter(self.sessions.values()))
            source.activity_peers = tuple(self.sessions.values())
            self.shared_fund = SharedFund(source)
            for session in self.sessions.values():
                session.shared_fund = self.shared_fund
                session.fund_source = session is source
                if session is not source:
                    session.monitor._shared_fund = self.shared_fund

    def publish(self, uuid, kind, payload):
        try:
            self.events.put_nowait((uuid, kind, payload))
        except queue.Full:
            # UI is a latest-state consumer, never a backlog of input commands.
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
            try:
                self.events.put_nowait((uuid, kind, payload))
            except queue.Full:
                pass

    @property
    def any_real(self):
        return any(s.requested_real for s in self.sessions.values())

    @property
    def any_active(self):
        return any(s.active.is_set() for s in self.sessions.values())

    def start(self):
        for session in self.sessions.values():
            session.start()

    def pause(self):
        for session in self.sessions.values():
            session.pause()

    def reset_cycle(self):
        if hasattr(self, 'shared_fund'):
            self.shared_fund.invalidate()
        for session in self.sessions.values():
            session.reset_cycle()

    def set_real_mode(self, enabled):
        for session in self.sessions.values():
            session.request_mode(enabled)
        return True, 'Режим применён ко всем выбранным окнам'

    def update_settings(self, settings):
        for session in self.sessions.values():
            session.monitor._tap_cancel.set()
            session.monitor.user_range = settings
            session.settings = settings
            session.settings_version += 1
            # Reconfirm on an independent frame after changing shared settings.
            session.mode_version += 1

    def emergency_stop(self):
        for session in self.sessions.values():
            session.stop()
            session.monitor.emergency_stop()

    def close(self):
        for session in self.sessions.values():
            session.stop()
        for session in self.sessions.values():
            if session.thread is not None:
                session.thread.join()
            else:
                session.monitor.close()
