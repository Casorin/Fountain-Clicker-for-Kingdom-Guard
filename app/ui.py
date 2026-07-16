from __future__ import annotations

import json
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image

from app.config import AppConfig
from app.monitor import PollSnapshot, PrizeMonitor
from app.single_instance import InstanceMetadata, SingleInstanceManager


def _show_existing_instance_dialog(existing: InstanceMetadata | None) -> str:
    forced_action = os.environ.get("KGPM_EXISTING_INSTANCE_ACTION", "").strip().lower()
    if forced_action in {"open", "restart", "cancel"}:
        return forced_action

    root = tk.Tk()
    root.withdraw()
    result = {"action": "cancel"}

    dialog = tk.Toplevel(root)
    dialog.title("Kingdom Guard Prize Monitor")
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()

    message = "Kingdom Guard Prize Monitor уже запущен."
    if existing is not None:
        message += f"\n\nPID: {existing.pid}"

    frame = ttk.Frame(dialog, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=message, justify="left").pack(anchor="w")

    buttons = ttk.Frame(frame)
    buttons.pack(anchor="e", pady=(16, 0))

    def choose(action: str) -> None:
        result["action"] = action
        dialog.destroy()

    ttk.Button(buttons, text="Открыть существующее окно", command=lambda: choose("open")).pack(side="left")
    ttk.Button(buttons, text="Перезапустить программу", command=lambda: choose("restart")).pack(side="left", padx=8)
    ttk.Button(buttons, text="Отмена", command=lambda: choose("cancel")).pack(side="left")

    dialog.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))
    dialog.update_idletasks()
    width = dialog.winfo_width()
    height = dialog.winfo_height()
    screen_width = dialog.winfo_screenwidth()
    screen_height = dialog.winfo_screenheight()
    x = max(0, int((screen_width - width) / 2))
    y = max(0, int((screen_height - height) / 3))
    dialog.geometry(f"+{x}+{y}")
    dialog.wait_window()
    root.destroy()
    return result["action"]


def _start_or_focus_existing_instance(config: AppConfig, manager: SingleInstanceManager) -> SingleInstanceManager | None:
    acquired, existing = manager.try_acquire()
    if acquired:
        return manager

    action = _show_existing_instance_dialog(existing)
    if action == "open":
        if existing is not None and existing.hwnd:
            SingleInstanceManager.bring_window_to_front(existing.hwnd)
        elif existing is not None and existing.pid:
            messagebox.showwarning("Kingdom Guard Prize Monitor", "Не удалось найти HWND существующего окна.")
        return None

    if action == "restart":
        if existing is None or not SingleInstanceManager.process_is_running(existing.pid):
            manager.remove_stale_metadata()
        else:
            if existing.hwnd:
                SingleInstanceManager.request_close(existing.hwnd)
            if not SingleInstanceManager.wait_for_exit(existing.pid, timeout_seconds=8.0):
                messagebox.showerror(
                    "Kingdom Guard Prize Monitor",
                    "Не удалось корректно закрыть старый экземпляр. Закройте его вручную и повторите запуск.",
                )
                return None
            manager.remove_stale_metadata()

        retry = SingleInstanceManager(config.instance_state_path)
        acquired_retry, _ = retry.try_acquire()
        if acquired_retry:
            return retry
        messagebox.showerror(
            "Kingdom Guard Prize Monitor",
            "После перезапуска экземпляр всё ещё занят. Попробуйте снова через несколько секунд.",
        )
        retry.release()
        return None

    return None


class LogPanel(ttk.LabelFrame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, text="Логи", padding=8)
        self.follow_logs = True
        self._inserting = False

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="К последним логам", command=self.go_to_latest).pack(side="left")
        ttk.Button(toolbar, text="Копировать всё", command=self.copy_all).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Очистить отображение", command=self.clear_display).pack(side="left", padx=(6, 0))
        self.new_entries_button = ttk.Button(
            toolbar,
            text="Есть новые записи ↓",
            command=self.go_to_latest,
        )

        text_frame = ttk.Frame(self)
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(
            text_frame,
            wrap="word",
            state="disabled",
            undo=False,
            width=58,
            height=20,
        )
        self.scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self._on_yview)
        self.text.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.text.bind("<MouseWheel>", self._on_user_scroll, add="+")
        self.text.bind("<Button-4>", self._on_user_scroll, add="+")
        self.text.bind("<Button-5>", self._on_user_scroll, add="+")
        self.text.bind("<KeyRelease>", self._on_user_scroll, add="+")

    def _on_yview(self, first: str, last: str) -> None:
        self.scrollbar.set(first, last)
        if self._inserting:
            return
        self._set_follow(float(last) >= 0.995)

    def _on_user_scroll(self, _event: tk.Event | None = None) -> None:
        self.after_idle(self._sync_follow_from_view)

    def _sync_follow_from_view(self) -> None:
        self._set_follow(self.text.yview()[1] >= 0.995)

    def _set_follow(self, enabled: bool) -> None:
        self.follow_logs = enabled
        if enabled:
            self.new_entries_button.pack_forget()
        elif not self.new_entries_button.winfo_manager():
            self.new_entries_button.pack(side="right")

    def append(self, line: str) -> None:
        at_bottom = self.follow_logs and self.text.yview()[1] >= 0.995
        top_index = self.text.index("@0,0")
        self._inserting = True
        try:
            self.text.configure(state="normal")
            self.text.insert("end", line)
            self.text.configure(state="disabled")
            if at_bottom:
                self.text.see("end")
            else:
                self.text.yview(top_index)
        finally:
            self._inserting = False
        if at_bottom:
            self._set_follow(True)
        else:
            self._set_follow(False)

    def go_to_latest(self) -> None:
        self.text.see("end")
        self._set_follow(True)

    def copy_all(self) -> None:
        content = self.text.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(content)
        self.update_idletasks()

    def clear_display(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self._set_follow(True)


class AppWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = AppConfig()
        self.monitor = PrizeMonitor(self.config)
        self.running = False
        self.ocr_warmup_complete = False
        self.ocr_warmup_error: str | None = None
        self.ocr_warmup_report: dict[str, object] = {}
        self._warmup_start_requested = os.environ.get("KGPM_AUTO_START", "0") == "1"
        self._warmup_thread: threading.Thread | None = None
        self.close_callback = None
        acceptance_path = os.environ.get("KGPM_ACCEPTANCE_LOG", "").strip()
        self._acceptance_log_path = Path(acceptance_path) if acceptance_path else None
        self._acceptance_started_monotonic: float | None = None
        self._acceptance_poll_count = 0
        self._acceptance_control_images = 0
        self._acceptance_min_seconds = float(os.environ.get("KGPM_ACCEPTANCE_MIN_SECONDS", "600"))
        self.logs_visible = False
        self._closed_window_width = 1100

        self.root.title("Kingdom Guard Prize Monitor")
        self.root.geometry("1100x980")
        self.root.minsize(1100, 980)

        self.connection_var = tk.StringVar(value="Проверка...")
        self.value_var = tk.StringVar(value="—")
        self.status_var = tk.StringVar(value="Ожидание")
        self.phase_var = tk.StringVar(value=self.monitor.state.phase.value)
        self.mode_var = tk.BooleanVar(value=False)
        self.mode_label_var = tk.StringVar(value="Тестовый режим")
        self.mode_banner_var = tk.StringVar(value=self.monitor.mode_banner())
        self.range_var = tk.StringVar(value=self.monitor.target_range_label())
        self.tap_policy_var = tk.StringVar(value=self.monitor.real_taps_label())
        self.confirmations_var = tk.StringVar(value="0")
        self.screen_var = tk.StringVar(value="Не проверено")
        self.button_var = tk.StringVar(value="Не проверено")
        self.ocr_var = tk.StringVar(value="Не проверено")
        self.last_reset_var = tk.StringVar(value="неизвестно")
        self.since_reset_var = tk.StringVar(value="—")
        self.cooldown_var = tk.StringVar(value="—")
        self.active_burst_var = tk.StringVar(value="0")
        self.total_taps_var = tk.StringVar(value="0")
        self.reset_since_var = tk.StringVar(value="неизвестно")
        self.reset_average_var = tk.StringVar(value="недостаточно данных")
        self.reset_min_var = tk.StringVar(value="недостаточно данных")
        self.reset_max_var = tk.StringVar(value="недостаточно данных")
        self.active_range_var = tk.StringVar(value=self.monitor.target_range_label())
        self.test_range_min_var = tk.StringVar(value=str(self.monitor.user_range.test_min_prize))
        self.test_range_max_var = tk.StringVar(value=str(self.monitor.user_range.test_max_prize))
        self.log_toggle_var = tk.StringVar(value="Показать логи")

        self._build()
        self._bind_hotkeys()
        self._connect()
        self._refresh_static_panels()
        self._start_ocr_warmup()

    def _build(self) -> None:
        self.paned = ttk.PanedWindow(self.root, orient="horizontal")
        self.paned.pack(fill="both", expand=True)
        frame = ttk.Frame(self.paned, padding=12)
        self.main_frame = frame
        self.paned.add(frame, weight=1)
        self.log_panel = LogPanel(self.paned)
        self.log = self.log_panel.text

        info = ttk.Frame(frame)
        info.pack(fill="x")

        mode_frame = ttk.LabelFrame(frame, text="Режим и диапазон", padding=8)
        mode_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(mode_frame, textvariable=self.mode_banner_var, font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(mode_frame, textvariable=self.range_var, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(2, 0))
        ttk.Label(mode_frame, textvariable=self.tap_policy_var, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(2, 0))

        ttk.Label(info, text="Статус MEmu:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Label(info, textvariable=self.connection_var).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(info, text="Последнее значение:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Label(info, textvariable=self.value_var).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(info, text="Видимость призового фонда:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Label(info, textvariable=self.ocr_var).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(info, text="Состояние:").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Label(info, textvariable=self.phase_var).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(info, text="Подтверждения:").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Label(info, textvariable=self.confirmations_var).grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(info, text="Экран события:").grid(row=0, column=2, sticky="w", padx=(28, 8), pady=4)
        ttk.Label(info, textvariable=self.screen_var).grid(row=0, column=3, sticky="w", pady=4)
        ttk.Label(info, text="Кнопка:").grid(row=1, column=2, sticky="w", padx=(28, 8), pady=4)
        ttk.Label(info, textvariable=self.button_var).grid(row=1, column=3, sticky="w", pady=4)
        ttk.Label(info, text="Режим:").grid(row=2, column=2, sticky="w", padx=(28, 8), pady=4)
        ttk.Label(info, textvariable=self.mode_label_var).grid(row=2, column=3, sticky="w", pady=4)
        ttk.Label(info, text="Статус:").grid(row=3, column=2, sticky="w", padx=(28, 8), pady=4)
        ttk.Label(info, textvariable=self.status_var).grid(row=3, column=3, sticky="w", pady=4)
        ttk.Label(info, text="Последнее обнуление:").grid(row=4, column=2, sticky="w", padx=(28, 8), pady=4)
        ttk.Label(info, textvariable=self.last_reset_var).grid(row=4, column=3, sticky="w", pady=4)
        ttk.Label(info, text="Прошло после reset:").grid(row=5, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Label(info, textvariable=self.since_reset_var).grid(row=5, column=1, sticky="w", pady=4)
        ttk.Label(info, text="До разрешения кликов:").grid(row=5, column=2, sticky="w", padx=(28, 8), pady=4)
        ttk.Label(info, textvariable=self.cooldown_var).grid(row=5, column=3, sticky="w", pady=4)
        ttk.Label(info, text="Активная серия:").grid(row=6, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Label(info, textvariable=self.active_burst_var).grid(row=6, column=1, sticky="w", pady=4)
        ttk.Label(info, text="Всего tap за сеанс:").grid(row=6, column=2, sticky="w", padx=(28, 8), pady=4)
        ttk.Label(info, textvariable=self.total_taps_var).grid(row=6, column=3, sticky="w", pady=4)

        controls = ttk.Frame(frame, padding=(0, 12, 0, 12))
        controls.pack(fill="x")
        ttk.Button(controls, text="Запустить мониторинг", command=self.start).pack(side="left")
        ttk.Button(controls, text="Пауза", command=self.pause).pack(side="left", padx=8)
        ttk.Button(controls, text="Сбросить состояние", command=self.reset_lock).pack(side="left", padx=8)
        ttk.Checkbutton(
            controls,
            text="Реальный режим",
            variable=self.mode_var,
            command=self._sync_mode,
        ).pack(side="left", padx=16)
        self.log_toggle_button = ttk.Button(
            controls,
            textvariable=self.log_toggle_var,
            command=self.toggle_logs,
        )
        self.log_toggle_button.pack(side="right")

        range_frame = ttk.LabelFrame(frame, text="Настройка диапазона кликов", padding=8)
        range_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(range_frame, text="Минимальное значение:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(range_frame, textvariable=self.test_range_min_var, width=12).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(range_frame, text="Максимальное значение:").grid(row=0, column=2, sticky="w", padx=(20, 8), pady=2)
        ttk.Entry(range_frame, textvariable=self.test_range_max_var, width=12).grid(row=0, column=3, sticky="w", pady=2)
        ttk.Button(range_frame, text="Применить", command=self.apply_range).grid(row=0, column=4, sticky="w", padx=(20, 0), pady=2)
        ttk.Label(range_frame, text="Активный диапазон:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 2))
        ttk.Label(range_frame, textvariable=self.active_range_var, font=("Segoe UI", 11, "bold")).grid(
            row=1,
            column=1,
            columnspan=4,
            sticky="w",
            pady=(8, 2),
        )

        stats_frame = ttk.LabelFrame(frame, text="СТАТИСТИКА ОБНУЛЕНИЙ", padding=8)
        stats_frame.pack(fill="x", pady=(0, 10))
        stats_frame.columnconfigure(1, weight=1)
        ttk.Label(stats_frame, text="С последнего обнуления:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(stats_frame, textvariable=self.reset_since_var).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(stats_frame, text="Средний интервал:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(stats_frame, textvariable=self.reset_average_var).grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(stats_frame, text="Минимальный интервал:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(stats_frame, textvariable=self.reset_min_var).grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(stats_frame, text="Максимальный интервал:").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(stats_frame, textvariable=self.reset_max_var).grid(row=3, column=1, sticky="w", pady=2)
        ttk.Label(stats_frame, text="Последние 10 подтверждённых обнулений:").grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(8, 4),
        )

        self.history_table = ttk.Treeview(
            stats_frame,
            columns=("index", "time", "peak", "interval"),
            show="headings",
            height=10,
        )
        self.history_table.heading("index", text="№")
        self.history_table.heading("time", text="Время обнуления")
        self.history_table.heading("peak", text="Пик перед обнулением")
        self.history_table.heading("interval", text="Интервал от предыдущего")
        self.history_table.column("index", width=50, anchor="center", stretch=False)
        self.history_table.column("time", width=180, anchor="center", stretch=False)
        self.history_table.column("peak", width=170, anchor="center", stretch=False)
        self.history_table.column("interval", width=220, anchor="w")
        self.history_table.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.history_table.insert("", "end", iid="placeholder", values=("—", "—", "—", "пока нет данных"))

        history_actions = ttk.Frame(stats_frame)
        history_actions.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.delete_history_button = ttk.Button(
            history_actions,
            text="Удалить выбранную запись",
            command=self.delete_selected_history_entry,
        )
        self.delete_history_button.pack(side="left")
        self.clear_history_button = ttk.Button(
            history_actions,
            text="Очистить всю историю",
            command=self.clear_all_history,
        )
        self.clear_history_button.pack(side="left", padx=(8, 0))

    def _bind_hotkeys(self) -> None:
        self.root.bind("<F8>", lambda _event: self.toggle())
        self.root.bind("<F9>", lambda _event: self.emergency_stop())

    def _sync_mode(self) -> None:
        enabled = self.mode_var.get()
        if enabled:
            active_range = self.monitor.target_range_label()
            approved = messagebox.askyesno(
                "Подтверждение реального режима",
                "Будет включён реальный режим.\n"
                f"Активный диапазон: {active_range}.\n"
                "Каждый настоящий tap расходует игровую валюту.\n"
                "Продолжить?",
                icon="warning",
            )
            if not approved:
                self.mode_var.set(False)
                enabled = False
        _changed, message = self.monitor.set_real_mode(enabled)
        self.mode_var.set(self.monitor.state.real_mode_armed)
        self.mode_label_var.set("Реальный режим" if self.monitor.state.real_mode_armed else "Тестовый режим")
        self.mode_banner_var.set(self.monitor.mode_banner())
        self.range_var.set(f"Диапазон: {self.monitor.target_range_label()}")
        self.active_range_var.set(self.monitor.target_range_label())
        self.tap_policy_var.set(self.monitor.real_taps_label())
        if message:
            self._append_log(message)

    def apply_range(self) -> None:
        try:
            min_value = int(self.test_range_min_var.get().strip())
            max_value = int(self.test_range_max_var.get().strip())
        except ValueError:
            messagebox.showerror("Ошибка диапазона", "Минимальное и максимальное значения должны быть целыми числами.")
            return

        if self.monitor.state.real_mode_armed:
            approved = messagebox.askyesno(
                "Изменение диапазона в реальном режиме",
                "Сейчас активен REAL MODE.\n"
                f"Новый диапазон будет применён и в TEST MODE, и в REAL MODE.\n"
                f"Новый диапазон: {min_value:,} - {max_value:,}.\n"
                "Продолжить?",
                icon="warning",
            )
            if not approved:
                return

        ok, message = self.monitor.update_test_range(min_value, max_value)
        if not ok:
            messagebox.showerror("Ошибка диапазона", message)
            return

        self.range_var.set(f"Диапазон: {self.monitor.target_range_label()}")
        self.active_range_var.set(self.monitor.target_range_label())
        self._append_log(message)

    def _connect(self) -> None:
        ok, message = self.monitor.connect()
        self.connection_var.set("Подключено" if ok else f"Ошибка: {message}")
        self._append_log(message)

    def _append_log(self, text: str) -> None:
        timestamp = self.monitor.timestamp()
        self.log_panel.append(f"[{timestamp}] {text}\n")

    def toggle_logs(self) -> None:
        self.root.update_idletasks()
        if self.logs_visible:
            self.paned.forget(self.log_panel)
            self.logs_visible = False
            self.log_toggle_var.set("Показать логи")
            self.root.minsize(1100, 980)
            self.root.geometry(f"{self._closed_window_width}x{self.root.winfo_height()}")
            return

        self._closed_window_width = max(1100, self.root.winfo_width())
        self.paned.add(self.log_panel, weight=0)
        self.logs_visible = True
        self.log_toggle_var.set("Скрыть логи")
        target_width = max(1500, self._closed_window_width + 500)
        self.root.minsize(1500, 980)
        self.root.geometry(f"{target_width}x{self.root.winfo_height()}")
        self.root.update_idletasks()
        try:
            self.paned.sashpos(0, max(1000, target_width - 500))
        except tk.TclError:
            pass

    @staticmethod
    def _user_visible_ocr_text(snapshot: PollSnapshot) -> str:
        if snapshot.ocr_status.value == "Число видно":
            return "Число видно"
        if snapshot.ocr_status.value == "Закрыто уведомлением":
            return "Закрыто уведомлением (текущий OCR: отсутствует)"
        if snapshot.ocr_status.value == "Windows OCR timeout":
            return "OCR timeout"
        if snapshot.ocr_status.value == "Ошибка распознавания":
            return "Ошибка распознавания"
        return "Не удалось определить"

    def _reload_history_table(self, rows: list[tuple[str, str, str, str]]) -> None:
        for item in self.history_table.get_children():
            self.history_table.delete(item)
        if not rows:
            self.history_table.insert("", "end", iid="placeholder", values=("—", "—", "—", "пока нет данных"))
            return
        for index, row in enumerate(rows):
            self.history_table.insert("", "end", iid=f"event-{index}", values=row)

    def delete_selected_history_entry(self) -> None:
        selection = self.history_table.selection()
        if not selection:
            messagebox.showwarning("Удаление записи", "Сначала выберите запись в таблице.")
            return
        item_id = selection[0]
        if item_id == "placeholder" or not item_id.startswith("event-"):
            messagebox.showwarning("Удаление записи", "Для удаления нужно выбрать реальную production-запись.")
            return
        try:
            visible_index = int(item_id.split("-", 1)[1])
        except ValueError:
            messagebox.showerror("Удаление записи", "Не удалось определить выбранную запись.")
            return
        if visible_index >= len(self.monitor.reset_history):
            messagebox.showerror("Удаление записи", "Выбранная запись больше не актуальна. Обновите таблицу.")
            self._reload_history_table(self.monitor._history_rows())
            return

        event = self.monitor.reset_history[visible_index]
        peak_text = f"{event.peak_before_reset:,}".replace(",", " ") if event.peak_before_reset is not None else "нет данных"
        approved = messagebox.askyesno(
            "Подтверждение удаления",
            "Удалить запись обнуления?\n\n"
            f"Время: {datetime.fromisoformat(event.timestamp_reset).astimezone(self.monitor._local_zone()).strftime('%H:%M:%S')}\n"
            f"Пик перед обнулением: {peak_text}\n\n"
            "Это действие удалит запись из production-истории.",
            icon="warning",
        )
        if not approved:
            return

        success, message = self.monitor.delete_reset_history_entry(visible_index)
        if not success:
            messagebox.showerror("Удаление записи", message)
            return
        self._refresh_static_panels()
        self._append_log(message)

    def clear_all_history(self) -> None:
        if not self.monitor.reset_history:
            messagebox.showinfo("Очистка истории", "Production-история уже пуста.")
            return
        approved = messagebox.askyesno(
            "Очистить всю историю",
            "Вы действительно хотите удалить ВСЮ production-историю обнулений?\n\n"
            "Будут удалены все записи из пользовательской статистики.\n"
            "Перед удалением будет создана резервная копия.",
            icon="warning",
        )
        if not approved:
            return

        success, message = self.monitor.clear_reset_history()
        if not success:
            messagebox.showerror("Очистка истории", message)
            return
        self._refresh_static_panels()
        self._append_log(message)

    def _refresh_static_panels(self) -> None:
        now = self.monitor._now()
        self.last_reset_var.set(self.monitor._format_reset_time())
        self.since_reset_var.set(self.monitor._format_since_reset_label(now))
        self.cooldown_var.set(
            self.monitor._format_duration(self.monitor._cooldown_remaining(now))
            if self.monitor._cooldown_remaining(now) is not None
            else "—"
        )
        self.mode_banner_var.set(self.monitor.mode_banner())
        self.range_var.set(f"Диапазон: {self.monitor.target_range_label()}")
        if self.monitor.state.test_mode:
            self.active_range_var.set(self.monitor.editable_test_range_label())
        else:
            self.active_range_var.set(self.monitor.target_range_label())
        self.tap_policy_var.set(self.monitor.real_taps_label())
        avg_label, min_label, max_label = self.monitor._history_stats()
        self.reset_since_var.set(self.monitor._history_since_reset_label(now))
        self.reset_average_var.set(avg_label)
        self.reset_min_var.set(min_label)
        self.reset_max_var.set(max_label)
        self._reload_history_table(self.monitor._history_rows())

    def _refresh_runtime_panels(self) -> None:
        now = self.monitor._now()
        self.value_var.set(str(self.monitor.state.last_value) if self.monitor.state.last_value is not None else "—")
        self.ocr_var.set("Не проверено" if self.monitor.state.last_value is None else self.monitor.state.ocr_status.value)
        self.status_var.set(self.monitor.state.last_status)
        self.phase_var.set(self.monitor.state.phase.value)
        self.confirmations_var.set(str(self.monitor.state.candidate_hits))
        self.screen_var.set("Не проверено")
        self.button_var.set("Не проверено")
        self.last_reset_var.set(self.monitor._format_reset_time())
        self.since_reset_var.set(self.monitor._format_since_reset_label(now))
        self.cooldown_var.set(
            self.monitor._format_duration(self.monitor._cooldown_remaining(now))
            if self.monitor._cooldown_remaining(now) is not None
            else "—"
        )
        self.active_burst_var.set(str(self.monitor.state.burst_taps_done))
        self.total_taps_var.set(str(self.monitor.state.total_taps))
        self.mode_banner_var.set(self.monitor.mode_banner())
        self.range_var.set(f"Диапазон: {self.monitor.target_range_label()}")
        if self.monitor.state.test_mode:
            self.active_range_var.set(self.monitor.editable_test_range_label())
        else:
            self.active_range_var.set(self.monitor.target_range_label())
        self.tap_policy_var.set(self.monitor.real_taps_label())

    def _apply_snapshot(self, snapshot: PollSnapshot) -> None:
        self.value_var.set(str(snapshot.value) if snapshot.value is not None else "—")
        self.ocr_var.set(self._user_visible_ocr_text(snapshot))
        self.status_var.set(snapshot.status)
        self.phase_var.set(snapshot.phase.value)
        self.confirmations_var.set(str(snapshot.confirmation_hits))
        self.screen_var.set(
            f"{'подтверждён' if snapshot.event_screen_ok else 'не подтверждён'} "
            f"(anchor={snapshot.screen_anchor_score:.2f})"
        )
        self.button_var.set(
            f"{'подтверждена' if snapshot.button_visible else 'не подтверждена'} "
            f"(button={snapshot.button_score:.2f})"
        )
        self.last_reset_var.set(snapshot.last_reset_at)
        self.since_reset_var.set(snapshot.since_reset_label)
        self.cooldown_var.set(snapshot.cooldown_label)
        self.active_burst_var.set(str(snapshot.active_burst_taps))
        self.total_taps_var.set(str(snapshot.total_taps))
        self.mode_banner_var.set(snapshot.mode_banner)
        self.range_var.set(f"Диапазон: {snapshot.target_range_label}")
        if self.monitor.state.test_mode:
            self.active_range_var.set(snapshot.editable_test_range_label)
        else:
            self.active_range_var.set(snapshot.target_range_label)
        self.tap_policy_var.set(snapshot.real_taps_label)
        self.reset_since_var.set(snapshot.reset_since_history_label)
        self.reset_average_var.set(snapshot.reset_average_label)
        self.reset_min_var.set(snapshot.reset_min_label)
        self.reset_max_var.set(snapshot.reset_max_label)
        self._reload_history_table(snapshot.reset_history_rows)

        display_value_text = str(snapshot.value) if snapshot.value is not None else "не распознано"
        current_ocr_text = str(snapshot.raw_value) if snapshot.raw_value is not None else "отсутствует"
        self._append_log(
            f"display_value={display_value_text}; current_ocr={current_ocr_text}; "
            f"ocr={snapshot.ocr_status.value}; prefilter={snapshot.prefilter_status}; "
            f"phase={snapshot.phase.value}; hits={snapshot.confirmation_hits}; "
            f"screen={snapshot.event_screen_ok}; button={snapshot.button_visible}"
        )
        if snapshot.would_tap and not snapshot.clicked:
            self._append_log("ТЕСТОВЫЙ РЕЖИМ: серия tap только симулирована")
        for event in snapshot.tap_events:
            self._append_log(event)
        if snapshot.diagnostics_dir:
            self._append_log(f"Диагностика сохранена: {snapshot.diagnostics_dir}")
        self._record_acceptance_poll(snapshot)

    def _record_acceptance_poll(self, snapshot: PollSnapshot) -> None:
        if self._acceptance_log_path is None or self._acceptance_started_monotonic is None:
            return
        production = self.monitor._last_production_ocr
        paddle_value = (
            production.paddle.value
            if production is not None and production.paddle is not None
            else None
        )
        rapid_value = (
            production.rapid.value
            if production is not None and production.rapid is not None
            else None
        )
        row = {
            "timestamp": snapshot.timestamp,
            "rapidocr_value": rapid_value,
            "paddleocr_value": paddle_value,
            "current_ocr_value": snapshot.raw_value,
            "display_value": snapshot.value,
            "trusted_value": snapshot.trusted_value,
            "notification_veto": snapshot.notification_veto,
            "notification_recovery_hits": snapshot.notification_recovery_hits,
            "screen_ok": snapshot.event_screen_ok,
            "button_ok": snapshot.button_visible,
            "prefilter_diagnostic": snapshot.prefilter_status,
            "phase": snapshot.phase.value,
            "last_status": snapshot.status,
            "capture_latency_ms": snapshot.capture_ms,
            "ocr_latency_ms": snapshot.authoritative_ocr_ms,
            "ocr_method": snapshot.recognition.method,
        }
        with self._acceptance_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._acceptance_poll_count += 1

        if (
            self._acceptance_control_images < 20
            and snapshot.raw_value is not None
            and not snapshot.notification_veto
            and self.monitor._latest_screen is not None
            and self.monitor._latest_prize_crop is not None
        ):
            target = self._acceptance_log_path.parent / "control_images"
            target.mkdir(parents=True, exist_ok=True)
            index = self._acceptance_control_images + 1
            stem = f"{index:02d}_{snapshot.raw_value}_{datetime.now().strftime('%H%M%S_%f')}"
            self.monitor._latest_screen.save(target / f"{stem}_screen.png")
            self.monitor._latest_prize_crop.save(target / f"{stem}_crop.png")
            self._acceptance_control_images = index

        elapsed = time.monotonic() - self._acceptance_started_monotonic
        if self._acceptance_poll_count >= 200 and elapsed >= self._acceptance_min_seconds:
            self.pause()
            summary = {
                "polls": self._acceptance_poll_count,
                "elapsed_seconds": round(elapsed, 3),
                "control_images": self._acceptance_control_images,
                "real_mode_armed": self.monitor.state.real_mode_armed,
                "tap_decisions_enabled": self.monitor.tap_decisions_enabled,
                "total_taps": self.monitor.state.total_taps,
            }
            (self._acceptance_log_path.parent / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def toggle(self) -> None:
        if self.running:
            self.pause()
        else:
            self.start()

    def start(self) -> None:
        if self.running:
            return
        if not self.ocr_warmup_complete:
            self._warmup_start_requested = True
            self.status_var.set("Прогрев RapidOCR и PaddleOCR...")
            return
        self.monitor.resume()
        self.running = True
        if self._acceptance_log_path is not None and self._acceptance_started_monotonic is None:
            self._acceptance_log_path.parent.mkdir(parents=True, exist_ok=True)
            self._acceptance_log_path.write_text("", encoding="utf-8")
            self._acceptance_started_monotonic = time.monotonic()
        self._append_log("Мониторинг запущен")
        self._schedule_tick()

    def _start_ocr_warmup(self) -> None:
        self.status_var.set("Прогрев RapidOCR и PaddleOCR...")

        def worker() -> None:
            try:
                crop_path = self.config.prize_crop_path
                if crop_path.exists():
                    crop = Image.open(crop_path).convert("RGB")
                    warmup_source = str(crop_path.resolve())
                else:
                    crop = Image.new("RGB", (self.config.prize_crop.width, self.config.prize_crop.height), (80, 80, 80))
                    warmup_source = "synthetic_read_only_crop"
                report = self.monitor._ocr_pipeline.engines.warm_up(crop)
                import paddleocr
                import rapidocr

                report.update(
                    {
                        "python": sys.executable,
                        "rapidocr_module": str(getattr(rapidocr, "__file__", "")),
                        "paddleocr_module": str(getattr(paddleocr, "__file__", "")),
                        "pipeline": type(self.monitor._ocr_pipeline).__name__,
                        "crop_path": warmup_source,
                    }
                )
                self.ocr_warmup_report = report
            except Exception as exc:
                self.ocr_warmup_error = f"{type(exc).__name__}: {exc}"

        self._warmup_thread = threading.Thread(target=worker, name="kgpm-ocr-warmup", daemon=True)
        self._warmup_thread.start()
        self.root.after(100, self._poll_ocr_warmup)

    def _poll_ocr_warmup(self) -> None:
        if self._warmup_thread is not None and self._warmup_thread.is_alive():
            self.root.after(100, self._poll_ocr_warmup)
            return
        if self.ocr_warmup_error:
            self.status_var.set(f"Ошибка прогрева OCR: {self.ocr_warmup_error}")
            self._write_runtime_status()
            return
        self.ocr_warmup_complete = True
        self.status_var.set("OCR готов. TEST MODE, реальные tap запрещены.")
        self._append_log(
            "OCR прогрет: "
            f"Rapid cold={self.ocr_warmup_report.get('rapid_cold_ms')} ms, "
            f"warm={self.ocr_warmup_report.get('rapid_warm_ms')} ms; "
            f"Paddle cold={self.ocr_warmup_report.get('paddle_cold_ms')} ms, "
            f"warm={self.ocr_warmup_report.get('paddle_warm_ms')} ms"
        )
        self._write_runtime_status()
        if os.environ.get("KGPM_CLOSE_AFTER_WARMUP", "0") == "1" and self.close_callback is not None:
            self.root.after(500, self.close_callback)
            return
        if self._warmup_start_requested:
            self.start()

    def _write_runtime_status(self) -> None:
        path = Path("runtime/gui_runtime_status.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "python": sys.executable,
            "title": self.root.title(),
            "hwnd": int(self.root.winfo_id()),
            "viewable": bool(self.root.winfo_viewable()),
            "geometry": self.root.geometry(),
            "ocr_warmup_complete": self.ocr_warmup_complete,
            "ocr_warmup_error": self.ocr_warmup_error,
            "ocr_warmup": self.ocr_warmup_report,
            "test_mode": self.monitor.state.test_mode,
            "real_mode_armed": self.monitor.state.real_mode_armed,
            "tap_decisions_enabled": self.monitor.tap_decisions_enabled,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def pause(self) -> None:
        self.running = False
        self.monitor.pause()
        self.status_var.set(self.monitor.state.last_status)
        self.phase_var.set(self.monitor.state.phase.value)
        self._append_log(self.monitor.state.last_status)

    def reset_lock(self) -> None:
        if self.monitor.state.real_mode_armed:
            approved = messagebox.askyesno(
                "Сбросить текущее состояние",
                "Сброс текущего состояния удалит информацию о последнем обнулении и текущем cooldown.\n\n"
                "Чтобы исключить преждевременные реальные клики, после сброса реальные tap останутся "
                "заблокированы до нового достоверно обнаруженного обнуления.\n\n"
                "Продолжить?",
                icon="warning",
            )
        else:
            approved = messagebox.askyesno(
                "Сбросить текущее состояние",
                "Сбросить текущее состояние монитора?\n\n"
                "Будут очищены:\n"
                "- текущее распознанное значение;\n"
                "- текущий пик;\n"
                "- время последнего reset;\n"
                "- cooldown;\n"
                "- внутреннее состояние текущего цикла.\n\n"
                "Production-история обнулений останется без изменений.",
                icon="warning",
            )
        if not approved:
            return
        self.monitor.reset_lock()
        self._refresh_runtime_panels()
        self._refresh_static_panels()
        self._append_log(self.monitor.state.last_status)

    def emergency_stop(self) -> None:
        self.running = False
        self.monitor.emergency_stop()
        self.monitor.close()
        self.status_var.set(self.monitor.state.last_status)
        self.phase_var.set(self.monitor.state.phase.value)
        self._append_log("Аварийная остановка (F9)")

    def _schedule_tick(self) -> None:
        if not self.running:
            return
        self._tick()
        self.root.after(self.config.poll_interval_ms, self._schedule_tick)

    def _tick(self) -> None:
        try:
            snapshot = self.monitor.poll_once()
        except Exception as exc:
            self.status_var.set("Ошибка мониторинга")
            self._append_log(f"Ошибка: {exc}")
            return
        self._apply_snapshot(snapshot)


def main() -> None:
    config = AppConfig()
    manager = SingleInstanceManager(config.instance_state_path)
    manager = _start_or_focus_existing_instance(config, manager)
    if manager is None:
        return

    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")

    app = AppWindow(root)
    root.deiconify()
    root.update_idletasks()
    root.update()
    root.lift()
    manager.register_window(root.winfo_id(), root.title())
    app._write_runtime_status()

    def on_close() -> None:
        app.monitor.close()
        manager.release()
        root.destroy()

    app.close_callback = on_close
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
