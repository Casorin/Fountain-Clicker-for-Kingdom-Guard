"""Application identity shared by the local and portable launchers."""
from pathlib import Path
import sys


ICON_PATH = Path(__file__).resolve().parents[1] / 'assets' / 'fountain.ico'


def set_window_icon(root):
    if sys.platform == 'win32' and ICON_PATH.exists():
        root.iconbitmap(str(ICON_PATH), default=str(ICON_PATH))


def set_taskbar_identity():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Casorin.Fountain.Clicker')
