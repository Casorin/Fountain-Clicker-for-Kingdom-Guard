"""Read-only wallet guard, independent of prize/reset recognition."""
import re
import time
import threading
from contextlib import nullcontext
from collections import deque
import numpy as np
from PIL import Image


def parse_balance(text):
    cleaned = re.sub(r"\s", "", str(text))
    return int(cleaned) if re.fullmatch(r"\d{1,7}", cleaned) else None


class GemGuard:
    def __init__(self, engines, clock=time.monotonic):
        self.engines = engines
        self.clock = clock
        self.checked_at = -float('inf')
        self.balance = None
        self.estimated = None
        self.error = None
        self.pending = deque()
        self._state_lock = threading.RLock()
        self._engine_lock = (vars(engines).get('_inference_lock') if engines is not None else None) or nullcontext()
        self._refresh_thread = None
        self.balance_frame_time = None
        self.read_ms = None

    def read(self, screen):
        with self._engine_lock:
            return self._read_balance(screen)

    def _read_balance(self, screen):
        # Supported Android profile: digits only, excludes the diamond and +.
        if screen.size != (1080, 1080):
            return None
        # Include the final digit of seven-digit balances, but stop before +.
        crop = screen.crop((945, 25, 1031, 55))
        roi = np.asarray(crop.resize((344, 120), Image.Resampling.LANCZOS))
        rapid = self.engines._rapid_engine()(roi, use_det=False, use_cls=False, use_rec=True)
        paddle = list(self.engines._paddle_engine().predict(roi))[0].json['res']
        rv = parse_balance(rapid.txts[0]) if rapid.txts else None
        pv = parse_balance(paddle.get('rec_text', ''))
        rc = float(rapid.scores[0]) if rapid.scores else 0.0
        if rv is not None and rv == pv and rc >= .90 and float(paddle.get('rec_score', 0)) >= .90:
            return rv
        return None

    def refresh_async(self, screen, interval=.5, frame_time=None):
        with self._state_lock:
            if ((self._refresh_thread is not None and self._refresh_thread.is_alive())
                    or self.clock()-self.checked_at < interval):
                return
            captured_at = self.clock() if frame_time is None else frame_time
            image = screen.copy()
            def worker():
                started = time.perf_counter()
                try:
                    value = self.read(image)
                    error = None if value is not None else 'balance not confirmed'
                except Exception as exc:
                    value, error = None, str(exc)
                with self._state_lock:
                    self.balance = value
                    self.error = error
                    self.checked_at = self.clock()
                    self.balance_frame_time = captured_at
                    self.read_ms = (time.perf_counter()-started)*1000
                    # Preserve every command sent after this image was captured.
                    while self.pending and self.pending[0] <= captured_at-.3:
                        self.pending.popleft()
                    self.estimated = max(0, value-100*len(self.pending)) if value is not None else None
            self._refresh_thread = threading.Thread(target=worker, name='kgpm-wallet-read', daemon=True)
            self._refresh_thread.start()

    def permits_cached(self, minimum, max_age=.75):
        with self._state_lock:
            if (self.estimated is None or self.balance_frame_time is None
                    or not 0 <= self.clock()-self.balance_frame_time <= max_age):
                return False, 'unknown'
            return (False, 'floor') if self.estimated-100 < minimum else (True, 'ok')

    def refresh(self, screen, interval=.5, frame_time=None):
        if self.clock()-self.checked_at < interval:
            return self.balance
        try:
            value = self.read(screen)
            self.error = None if value is not None else 'balance not confirmed'
        except Exception as exc:
            value = None
            self.error = str(exc)
        self.checked_at = self.clock()
        self.balance = value
        # A video frame can predate a sent input. Reserve unsettled commands,
        # then reconcile older ones with the actual wallet on the next frame.
        cutoff = (self.clock() if frame_time is None else frame_time)-.3
        while self.pending and self.pending[0] <= cutoff:
            self.pending.popleft()
        self.estimated = max(0,value-100*len(self.pending)) if value is not None else None
        return value

    def permits(self, screen, minimum, frame_time=None):
        self.refresh(screen,frame_time=frame_time)
        if self.estimated is None:
            return False, 'unknown'
        # Count every sent command as spent even when the game rejects it.
        if self.estimated-100 < minimum:
            return False, 'floor'
        return True, 'ok'

    def reserve_sent_tap(self):
        with self._state_lock:
            self.pending.append(self.clock())
            if self.estimated is not None:
                self.estimated = max(0, self.estimated-100)
