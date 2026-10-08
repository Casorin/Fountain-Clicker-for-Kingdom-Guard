from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from app.branding import ICON_PATH, set_window_icon
from scripts.build_portable import compile_launcher


class BrandingTests(unittest.TestCase):
    def test_icon_contains_small_and_large_windows_sizes(self):
        with Image.open(ICON_PATH) as icon:
            self.assertEqual(icon.format, 'ICO')
            self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)} <= icon.ico.sizes())

    def test_window_icon_can_be_applied(self):
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(root, 'iconbitmap', wraps=root.iconbitmap) as apply_icon:
                set_window_icon(root)
                apply_icon.assert_called_once_with(str(ICON_PATH), default=str(ICON_PATH))
            root.update_idletasks()
        finally:
            root.destroy()

    def test_build_embeds_icon_without_build_machine_runtime_paths(self):
        with tempfile.TemporaryDirectory() as directory, patch('scripts.build_portable.subprocess.run') as run:
            compile_launcher(Path(directory))
            arguments = run.call_args.args[0]
            self.assertIn('/win32icon:' + str(ICON_PATH), arguments)
            self.assertTrue(any(arg.startswith('/out:') and arg.endswith('.exe') for arg in arguments))
            run.assert_called_once()
