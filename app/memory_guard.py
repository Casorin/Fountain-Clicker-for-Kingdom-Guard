"""Read-only Windows commit headroom check before spawning a child process."""
import ctypes
import os


class MemoryStatus(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
        (name, ctypes.c_ulonglong) for name in (
            'total_physical', 'available_physical', 'total_commit', 'available_commit',
            'total_virtual', 'available_virtual', 'extended_virtual')]


def available_commit_bytes():
    if os.name != 'nt':
        return None
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.available_commit


def low_memory_message(available=None):
    if available is None:
        available = available_commit_bytes()
    if available is not None and available < 768 * 1024 * 1024:
        return ('Недостаточно памяти для подключения к эмулятору. '
                'Закройте лишние окна эмуляторов или другие программы и попробуйте снова. '
                'Нажатия остановлены.')
    return None
