import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from app.memu_windows import MemuWindow
from app.window_picker import WindowPicker


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.callback = Mock()
        with patch.object(WindowPicker, 'refresh'):
            self.picker = WindowPicker(self.root, 'adb.exe', '127.0.0.1:21503', self.callback)
        self.window = MemuWindow('MEmu_2', 'second', '127.0.0.1:21523')
        self.picker.results.put(('list', [self.window]))
        self.picker.collect()

    def tearDown(self):
        if self.picker.winfo_exists():
            self.picker.destroy()
        self.root.destroy()

    def test_preview_required_before_selection(self):
        self.picker.choose()
        self.callback.assert_not_called()
        self.assertTrue(self.picker.choose_button.instate(['disabled']))
        self.picker.results.put(('image', self.window.uuid, Image.new('RGB', (1080, 1080))))
        self.picker.checked.add(self.window.uuid)
        self.picker.collect()
        self.assertFalse(self.picker.choose_button.instate(['disabled']))
        self.picker.choose()
        self.callback.assert_called_once_with([self.window])

    def test_unsupported_size_cannot_start(self):
        self.picker.results.put(('image', self.window.uuid, Image.new('RGB', (200, 200))))
        self.picker.checked.add(self.window.uuid)
        self.picker.collect()
        self.picker.choose()
        self.callback.assert_not_called()
        self.assertTrue(self.picker.choose_button.instate(['disabled']))

    def test_buttons_remain_inside_small_window_with_large_preview(self):
        self.root.deiconify()
        self.picker.geometry('720x560')
        self.picker.results.put(('image', self.window.uuid, Image.new('RGB', (1080,1080))))
        self.picker.collect()
        self.root.update()
        for button in (self.picker.choose_button, self.picker.refresh_button):
            bottom = button.winfo_rooty()-self.picker.winfo_rooty()+button.winfo_height()
            self.assertLessEqual(bottom, self.picker.winfo_height())
            self.assertTrue(button.winfo_viewable())

    def test_two_checkboxes_choose_two_windows(self):
        second = MemuWindow('MEmu', 'first', '127.0.0.1:21503')
        self.picker.results.put(('list', [second, self.window]))
        for window in (second, self.window):
            self.picker.results.put(('image', window.uuid, Image.new('RGB', (1080,1080))))
        self.picker.collect()
        self.picker.checked = {second.uuid, self.window.uuid}
        self.picker.choose()
        self.callback.assert_called_once_with([second, self.window])

    def test_splitter_widens_name_panel_and_keeps_preview_visible(self):
        self.root.deiconify()
        self.root.update()
        before = self.picker.list.winfo_width()
        x, y = self.picker.panes.sash_coord(0)
        self.picker.panes.sash_place(0, x+90, y)
        self.root.update()
        self.assertGreater(self.picker.list.winfo_width(), before)
        self.assertGreater(self.picker.preview.winfo_width(), 150)
        self.assertTrue(self.picker.choose_button.winfo_viewable())

    def test_pink_scrollbar_handles_many_windows(self):
        self.root.deiconify()
        windows = [MemuWindow(f'Длинное имя окна {i}', str(i), f'127.0.0.1:{22000+i}') for i in range(30)]
        self.picker.results.put(('list', windows))
        self.picker.collect()
        self.root.update()
        self.assertTrue(self.picker.scrollbar.winfo_viewable())
        self.assertLess(self.picker.scrollbar.last, 1)
        self.picker.scrollbar.move(type('Event', (), {'y': self.picker.scrollbar.winfo_height()-12})())
        self.root.update()
        self.assertGreater(self.picker.list.yview()[0], 0)
