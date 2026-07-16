from __future__ import annotations

import subprocess
import threading
import atexit
from pathlib import Path


class AdbError(RuntimeError):
    pass


class AdbClient:
    def __init__(self, adb_path: Path, serial: str) -> None:
        self.adb_path = Path(adb_path)
        self.serial = serial
        self._shell: subprocess.Popen[bytes] | None = None
        self._shell_lock = threading.Lock()
        atexit.register(self.close_shell)

    def _run(self, *args: str, check: bool = True, timeout: float = 15.0) -> subprocess.CompletedProcess[bytes]:
        command = [str(self.adb_path), *args]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except OSError as exc:
            raise AdbError(f"Не удалось запустить adb: {exc}") from exc

        if check and completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            stdout = completed.stdout.decode("utf-8", errors="replace").strip()
            message = stderr or stdout or f"adb завершился с кодом {completed.returncode}"
            raise AdbError(message)

        return completed

    def connect(self) -> str:
        self._run("start-server")
        completed = self._run("connect", self.serial)
        return completed.stdout.decode("utf-8", errors="replace").strip()

    def devices(self) -> list[str]:
        completed = self._run("devices")
        lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
        devices: list[str] = []
        for line in lines[1:]:
            if not line.strip():
                continue
            serial, _, state = line.partition("\t")
            if state.strip() == "device":
                devices.append(serial.strip())
        return devices

    def capture_screen(self) -> bytes:
        completed = self._run("-s", self.serial, "exec-out", "screencap", "-p", timeout=20.0)
        data = completed.stdout
        if not data.startswith(b"\x89PNG"):
            raise AdbError("adb вернул данные, не похожие на PNG-скриншот")
        return data

    def capture_screen_raw(self) -> bytes:
        completed = self._run("-s", self.serial, "exec-out", "screencap", timeout=20.0)
        data = completed.stdout
        if len(data) < 16:
            raise AdbError("adb returned too few bytes for raw screencap")
        return data

    def tap(self, x: int, y: int) -> None:
        self._run("-s", self.serial, "shell", "input", "tap", str(x), str(y), timeout=10.0)

    def _persistent_shell(self) -> subprocess.Popen[bytes]:
        if self._shell is not None and self._shell.poll() is None:
            return self._shell
        self.close_shell()
        try:
            self._shell = subprocess.Popen(
                [str(self.adb_path), "-s", self.serial, "shell"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise AdbError(f"Could not start persistent adb shell: {exc}") from exc
        return self._shell

    def tap_persistent(self, x: int, y: int) -> None:
        command = f"input tap {int(x)} {int(y)}\n".encode("ascii")
        with self._shell_lock:
            shell = self._persistent_shell()
            if shell.stdin is None:
                raise AdbError("Persistent adb shell stdin is unavailable")
            try:
                shell.stdin.write(command)
                shell.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.close_shell()
                raise AdbError(f"Persistent adb shell write failed: {exc}") from exc

    def close_shell(self) -> None:
        shell = self._shell
        self._shell = None
        if shell is None:
            return
        if shell.stdin is not None:
            try:
                shell.stdin.close()
            except OSError:
                pass
        if shell.poll() is None:
            shell.terminate()
            try:
                shell.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                shell.kill()
