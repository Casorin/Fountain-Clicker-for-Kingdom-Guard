import tkinter as tk
from tkinter import ttk
import threading
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

    def test_repeated_open_and_close_reuses_styles_in_same_interpreter(self):
        before = set(ttk.Style(self.root).element_names())
        for _ in range(20):
            with patch.object(WindowPicker,'refresh'):
                picker = WindowPicker(self.root,'adb.exe',[],self.callback)
            self.root.update_idletasks()
            self.assertTrue(picker.choose_button.winfo_exists())
            picker.destroy()
        self.assertEqual(set(ttk.Style(self.root).element_names()), before)
        self.assertEqual(len(self.root._fountain_picker_styles), 1)

    def test_partially_constructed_picker_can_be_closed(self):
        partial = WindowPicker.__new__(WindowPicker)
        tk.Toplevel.__init__(partial,self.root)
        partial.grab_set()
        partial.destroy()
        self.assertFalse(partial.winfo_exists())
        self.assertIsNone(self.root.grab_current())

    def test_close_does_not_wait_for_slow_discovery(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def discover(*args, **kwargs):
            entered.set()
            release.wait(3)
            finished.set()
            return [self.window]
        with patch('app.window_picker.discover_windows',side_effect=discover), \
             patch('app.window_picker.preview_window') as preview:
            self.picker.refresh()
            self.assertTrue(entered.wait(1))
            self.root.update()
            self.picker.destroy()
            self.assertFalse(self.picker.winfo_exists())
            self.assertIsNone(self.root.grab_current())
            release.set()
            self.assertTrue(finished.wait(1))
            preview.assert_not_called()

    def test_refresh_has_immediate_loading_feedback_and_resets_when_done(self):
        self.picker.images[self.window.uuid] = Image.new('RGB',(1080,1080))
        with patch('app.window_picker.threading.Thread') as worker:
            self.picker.refresh()
            self.picker.refresh()
        self.assertEqual(worker.call_count, 1)
        self.assertTrue(self.picker.busy)
        self.assertEqual(self.picker.refresh_button.cget('text'), 'Обновляем снимки…')
        self.assertEqual(self.picker.refresh_button.cget('style'), 'Picker.Loading.TButton')
        self.assertTrue(self.picker.refresh_button.instate(['disabled']))
        self.assertEqual(self.picker.refresh_progress.winfo_manager(), 'pack')
        self.assertFalse(self.picker.images)
        texts = [self.picker.preview.itemcget(i,'text') for i in self.picker.preview.find_all()]
        self.assertIn('Получаем снимок…', texts)
        self.picker.results.put(('list',[self.window]))
        self.picker.results.put(('image',self.window.uuid,Image.new('RGB',(1080,1080))))
        self.picker.collect()
        self.assertEqual(float(self.picker.refresh_progress.cget('value')), 1)
        self.picker.results.put(('done',))
        self.picker.collect()
        self.assertFalse(self.picker.busy)
        self.assertFalse(self.picker.refresh_button.instate(['disabled']))
        self.assertEqual(self.picker.refresh_button.cget('text'), '↻  Обновить снимки')
        self.assertEqual(self.picker.refresh_progress.winfo_manager(), '')

    def test_loading_controls_fit_in_small_picker(self):
        self.root.deiconify()
        self.picker.geometry('720x560')
        with patch('app.window_picker.threading.Thread'):
            self.picker.refresh()
        self.root.update()
        progress_right = self.picker.refresh_progress.winfo_rootx()+self.picker.refresh_progress.winfo_width()
        controls = self.picker.choose_button.master
        cancel = next(child for child in controls.winfo_children()
                      if hasattr(child,'cget') and child.winfo_class() == 'TButton' and child.cget('text') == 'Отмена')
        self.assertLessEqual(progress_right, cancel.winfo_rootx())
        self.assertLessEqual(self.picker.choose_button.winfo_rootx()+self.picker.choose_button.winfo_width(),
                             self.picker.winfo_rootx()+self.picker.winfo_width())

    def test_disabled_choose_button_explains_missing_checkmarks(self):
        self.picker.checked.clear()
        self.picker.explain_disabled_choice()
        self.assertIn('Поставьте галочку', self.picker.status.get())
        self.callback.assert_not_called()

    def test_preview_error_is_retained_after_clicking_checkbox(self):
        from types import SimpleNamespace
        message = 'Нет подключения к эмулятору. Включите локальную отладку ADB.'
        self.picker.results.put(('error', self.window.uuid, message))
        self.picker.collect()
        with patch.object(self.picker.list, 'identify_column', return_value='#0'), \
             patch.object(self.picker.list, 'identify_row', return_value=self.window.uuid):
            self.picker.toggle_checked(SimpleNamespace(keysym='', x=1, y=1))
        self.assertEqual(self.picker.status.get(), message)
        self.assertEqual(self.picker.diagnostics, [('MEmu', message)])
        preview_text = [self.picker.preview.itemcget(item, 'text') for item in self.picker.preview.find_all()]
        self.assertIn('Не удалось получить снимок', preview_text)
        self.assertIn(message, preview_text)
        self.assertTrue(self.picker.choose_button.instate(['disabled']))

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
