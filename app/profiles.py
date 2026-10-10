"""Separate program workspaces and exclusive ownership of each Android endpoint."""
import hashlib
import re
from dataclasses import replace

from app.single_instance import SingleInstanceManager


def profile_config(base, profile="default"):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", profile):
        raise ValueError("Invalid profile identifier")
    if profile == "default":
        return base
    folder = base.runtime_dir / "groups" / profile
    changes = {"runtime_dir": folder}
    for field in ("screenshot_path", "prize_crop_path", "button_crop_path", "title_crop_path",
                  "debug_dir", "trigger_dir", "reset_diagnostics_dir", "state_path",
                  "instance_state_path", "reset_history_path", "test_reset_history_path", "user_config_path"):
        changes[field] = folder / getattr(base, field).name
    return replace(base, **changes)


def profile_mutex(profile):
    suffix = "" if profile == "default" else "-" + profile
    return "Local\\KingdomGuardPrizeMonitor" + suffix


class DeviceLeases:
    """Acquire/release on the GUI thread, after monitor workers have stopped."""
    def __init__(self, folder, manager_factory=SingleInstanceManager):
        self.folder = folder
        self.manager_factory = manager_factory
        self.held = []

    def acquire(self, serials):
        if self.held:
            raise RuntimeError("Release previous devices before selecting new ones")
        try:
            for serial in sorted(set(serials)):
                identity = hashlib.sha256(serial.encode("utf-8")).hexdigest()
                manager = self.manager_factory(self.folder / (identity + ".json"),
                    "Local\\KingdomGuardPrizeMonitor-device-" + identity)
                ok, _ = manager.try_acquire()
                if not ok:
                    manager.release()
                    raise RuntimeError("Это окно эмулятора уже используется другим окном программы. "
                                       "Сначала закройте его там или выберите другое окно.")
                self.held.append(manager)
        except Exception:
            self.release()
            raise

    def release(self):
        for manager in reversed(self.held):
            manager.release()
        self.held.clear()
