from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import unittest

from app.ui import AppWindow, LogPanel


class LogPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.geometry("900x500+10000+10000")
        self.paned = ttk.PanedWindow(self.root, orient="horizontal")
        self.paned.pack(fill="both", expand=True)
        self.main = ttk.Frame(self.paned, width=300)
        self.panel = LogPanel(self.paned)
        self.paned.add(self.main, weight=1)
        self.paned.add(self.panel, weight=1)
        self.root.update()

    def tearDown(self) -> None:
        self.root.destroy()

    def append_lines(self, start: int, stop: int) -> None:
        for number in range(start, stop + 1):
            self.panel.append(f"Test log line {number}\n")
        self.root.update()

    def top_line(self) -> int:
        return int(self.panel.text.index("@0,0").split(".", 1)[0])

    def test_a_follow_mode_stays_at_bottom_after_100_lines(self) -> None:
        self.append_lines(1, 100)

        self.assertTrue(self.panel.follow_logs)
        self.assertGreaterEqual(self.panel.text.yview()[1], 0.995)
        self.assertEqual(self.panel.text.cget("state"), "disabled")

    def test_b_new_lines_do_not_move_old_log_view(self) -> None:
        self.append_lines(1, 100)
        self.panel.text.yview("20.0")
        self.root.update()
        self.panel._sync_follow_from_view()
        before = self.top_line()

        self.append_lines(101, 120)
        after = self.top_line()

        self.assertFalse(self.panel.follow_logs)
        self.assertLessEqual(abs(after - before), 1)
        self.assertTrue(self.panel.new_entries_button.winfo_manager())

    def test_c_latest_button_restores_follow_mode(self) -> None:
        self.append_lines(1, 100)
        self.panel.text.yview("20.0")
        self.root.update()
        self.panel._sync_follow_from_view()

        self.panel.go_to_latest()
        self.root.update()

        self.assertTrue(self.panel.follow_logs)
        self.assertGreaterEqual(self.panel.text.yview()[1], 0.995)
        self.assertFalse(self.panel.new_entries_button.winfo_manager())

    def test_d_hiding_and_reopening_panel_preserves_logs(self) -> None:
        self.append_lines(1, 25)
        before = self.panel.text.get("1.0", "end-1c")

        self.paned.forget(self.panel)
        self.root.update()
        self.paned.add(self.panel, weight=1)
        self.root.update()

        self.assertEqual(self.panel.text.get("1.0", "end-1c"), before)
        self.assertTrue(self.panel.winfo_ismapped())

    def test_e_copy_all_places_complete_text_on_clipboard(self) -> None:
        self.append_lines(1, 10)

        self.panel.copy_all()
        copied = self.root.clipboard_get()

        self.assertIn("Test log line 1", copied)
        self.assertIn("Test log line 10", copied)

    def test_appwindow_toggle_maps_panel_and_preserves_main_width(self) -> None:
        self.append_lines(1, 5)
        self.paned.forget(self.panel)
        self.root.geometry("1100x980+10000+10000")
        self.root.update()
        app = object.__new__(AppWindow)
        app.root = self.root
        app.paned = self.paned
        app.log_panel = self.panel
        app.logs_visible = False
        app._closed_window_width = 1100
        app.log_toggle_var = tk.StringVar(self.root, value="Показать логи")

        app.toggle_logs()
        self.root.update()

        self.assertTrue(app.logs_visible)
        self.assertEqual(app.log_toggle_var.get(), "Скрыть логи")
        self.assertTrue(self.panel.winfo_ismapped())
        self.assertGreaterEqual(self.root.winfo_width(), 1500)
        self.assertGreaterEqual(self.paned.sashpos(0), 1000)

        app.toggle_logs()
        self.root.update()

        self.assertFalse(app.logs_visible)
        self.assertEqual(app.log_toggle_var.get(), "Показать логи")
        self.assertFalse(self.panel.winfo_ismapped())
        self.assertIn("Test log line 5", self.panel.text.get("1.0", "end-1c"))


if __name__ == "__main__":
    unittest.main()
