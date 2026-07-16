from __future__ import annotations

import atexit
import ctypes
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ERROR_ALREADY_EXISTS = 183
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259
SW_RESTORE = 9
SW_SHOW = 5
WM_CLOSE = 0x0010

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
kernel32.CreateMutexW.restype = ctypes.c_void_p
kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
kernel32.ReleaseMutex.restype = ctypes.c_bool
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.c_bool
kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
kernel32.GetExitCodeProcess.restype = ctypes.c_bool

user32.IsWindow.argtypes = [ctypes.c_void_p]
user32.IsWindow.restype = ctypes.c_bool
user32.IsIconic.argtypes = [ctypes.c_void_p]
user32.IsIconic.restype = ctypes.c_bool
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = ctypes.c_bool
user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
user32.PostMessageW.restype = ctypes.c_bool


@dataclass
class InstanceMetadata:
    pid: int
    hwnd: int
    title: str
    started_at: float
    updated_at: float


class SingleInstanceManager:
    def __init__(self, metadata_path: Path, mutex_name: str = "Local\\KingdomGuardPrizeMonitor") -> None:
        self.metadata_path = Path(metadata_path)
        self.mutex_name = mutex_name
        self.pid = os.getpid()
        self.handle: int | None = None
        self.owns_mutex = False
        self._released = False
        atexit.register(self.release)

    def try_acquire(self) -> tuple[bool, InstanceMetadata | None]:
        handle = kernel32.CreateMutexW(None, True, self.mutex_name)
        if not handle:
            raise OSError(f"CreateMutexW failed: {ctypes.get_last_error()}")
        self.handle = int(handle)
        error = ctypes.get_last_error()
        if error == ERROR_ALREADY_EXISTS:
            self.owns_mutex = False
            existing = self.load_metadata()
            self._close_handle()
            return False, existing

        self.owns_mutex = True
        self._purge_stale_metadata()
        self.write_metadata(hwnd=0, title="Kingdom Guard Prize Monitor")
        return True, None

    def register_window(self, hwnd: int, title: str) -> None:
        if self.owns_mutex:
            self.write_metadata(hwnd=hwnd, title=title)

    def load_metadata(self) -> InstanceMetadata | None:
        if not self.metadata_path.exists():
            return None
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            metadata = InstanceMetadata(
                pid=int(payload["pid"]),
                hwnd=int(payload.get("hwnd", 0)),
                title=str(payload.get("title", "")),
                started_at=float(payload.get("started_at", 0.0)),
                updated_at=float(payload.get("updated_at", 0.0)),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not self.process_is_running(metadata.pid):
            self.remove_stale_metadata()
            return None
        return metadata

    def write_metadata(self, hwnd: int, title: str) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        started_at = now
        existing = self.load_metadata()
        if existing is not None and existing.pid == self.pid and existing.started_at:
            started_at = existing.started_at
        payload = InstanceMetadata(
            pid=self.pid,
            hwnd=int(hwnd),
            title=title,
            started_at=started_at,
            updated_at=now,
        )
        self.metadata_path.write_text(json.dumps(asdict(payload), ensure_ascii=False, indent=2), encoding="utf-8")

    def remove_stale_metadata(self) -> None:
        try:
            self.metadata_path.unlink(missing_ok=True)
        except OSError:
            pass

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        metadata = self.load_metadata()
        if metadata is not None and metadata.pid == self.pid:
            self.remove_stale_metadata()
        if self.owns_mutex and self.handle:
            kernel32.ReleaseMutex(ctypes.c_void_p(self.handle))
        self._close_handle()

    def _close_handle(self) -> None:
        if self.handle:
            kernel32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None

    def _purge_stale_metadata(self) -> None:
        metadata = self.load_metadata()
        if metadata is None:
            return
        if not self.process_is_running(metadata.pid):
            self.remove_stale_metadata()

    @staticmethod
    def process_is_running(pid: int) -> bool:
        if pid <= 0:
            return False
        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not process:
            return False
        try:
            code = ctypes.c_uint32(0)
            if not kernel32.GetExitCodeProcess(process, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(process)

    @staticmethod
    def window_exists(hwnd: int) -> bool:
        return hwnd > 0 and bool(user32.IsWindow(ctypes.c_void_p(hwnd)))

    @staticmethod
    def bring_window_to_front(hwnd: int) -> bool:
        if not SingleInstanceManager.window_exists(hwnd):
            return False
        if user32.IsIconic(ctypes.c_void_p(hwnd)):
            user32.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)
        else:
            user32.ShowWindow(ctypes.c_void_p(hwnd), SW_SHOW)
        return bool(user32.SetForegroundWindow(ctypes.c_void_p(hwnd)))

    @staticmethod
    def request_close(hwnd: int) -> bool:
        if not SingleInstanceManager.window_exists(hwnd):
            return False
        return bool(user32.PostMessageW(ctypes.c_void_p(hwnd), WM_CLOSE, None, None))

    @staticmethod
    def wait_for_exit(pid: int, timeout_seconds: float = 8.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if not SingleInstanceManager.process_is_running(pid):
                return True
            time.sleep(0.1)
        return not SingleInstanceManager.process_is_running(pid)
