from __future__ import annotations

import json
import os
import sys
import threading
import time
import faulthandler
import argparse
import subprocess
import uuid
import tkinter as tk
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image

from app.config import AppConfig
from app.monitor import MonitorPhase, PollSnapshot, PrizeMonitor
from app.single_instance import InstanceMetadata, SingleInstanceManager
from app.stream_transport import FreshFrameUnavailable


def poll_delay_ms(phase: MonitorPhase, normal_delay_ms: int, fast_observation: bool = False) -> int:
    return 1 if phase == MonitorPhase.ACTIVE_CLICKING or fast_observation else normal_delay_ms


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

        retry = SingleInstanceManager(config.instance_state_path, manager.mutex_name)
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


class LogPanel(ttk.Frame):
    def __init__(self, parent: tk.Misc, on_close=None) -> None:
        super().__init__(parent, style='RoundedCard.TFrame', padding=8)
        self.follow_logs = True
        self._inserting = False
        header=ttk.Frame(self,style='Card.TFrame')
        header.pack(fill='x',pady=(0,6))
        ttk.Label(header,text='Журнал событий',style='Card.TLabel',font=('Bahnschrift',12,'bold')).pack(side='left')
        self.close_button=ttk.Button(header,text='×',style='Log.Tool.TButton',width=2,command=on_close or (lambda: None))
        self.close_button.pack(side='right')
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="К последним", style='Log.Tool.TButton',command=self.go_to_latest).pack(side="left")
        ttk.Button(toolbar, text="Копировать всё", style='Log.Tool.TButton',command=self.copy_all).pack(side="left", padx=(4, 0))
        ttk.Button(toolbar, text="Очистить отображение", style='Log.Tool.TButton',command=self.clear_display).pack(side="left", padx=(4, 0))
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
        from app.window_picker import PinkScrollbar
        self.scrollbar = PinkScrollbar(text_frame,self.text.yview,ttk.Style(self).lookup('Card.TFrame','background') or '#ffffff')
        self.text.configure(yscrollcommand=self._on_yview)
        self.scrollbar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
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
    def __init__(self, root: tk.Tk, config=None, profile="default") -> None:
        self.root = root
        self.profile = profile
        self.config = config or AppConfig()
        self.config = replace(self.config,stream_transport_enabled=True,
                              continuous_click_interval_seconds=.125,continuous_max_taps=0)
        self._base_config = self.config
        from app.profiles import DeviceLeases
        self._device_leases = DeviceLeases(AppConfig().runtime_dir / 'device_owners')
        self._selection_path = self.config.runtime_dir / 'window_selection.json'
        self._selection_error = ''
        self._selected_window = None
        self._selected_windows = []
        self._group = None
        self._session_snapshots = {}
        self._session_statuses = {}
        self._focus_uuid = None
        self._switching_window = False
        self._window_picker_active = False
        if self._selection_path.exists():
            from app.memu_windows import resolve_selections, config_for_window
            try:
                self._selected_windows = resolve_selections(self._selection_path, self.config.adb_path)
                self._selected_window = self._selected_windows[0] if self._selected_windows else None
                if self._selected_window is None:
                    self._selection_error = 'Выбранное окно MEmu закрыто. Нажмите «Выбрать окно».'
                else:
                    self.config = config_for_window(self._base_config, self._selected_window)
            except Exception:
                self._selection_error = 'Не удалось проверить выбранное окно. Нажмите «Выбрать окно».'
        elif profile != 'default':
            self._selection_error = 'Нажмите «Выбрать окно», чтобы подключить MEmu к этому окну программы.'
        if not self._selection_error:
            try:
                serials = ([identity for w in self._selected_windows for identity in (w.serial, 'device:' + w.uuid)]
                           or [self.config.adb_serial])
                self._device_leases.acquire(serials)
            except Exception as exc:
                self._selection_error = str(exc)
        self.monitor = PrizeMonitor(self.config)
        self._poll_thread: threading.Thread | None = None
        self._poll_result = None
        self._poll_error = None
        self._cleanup_thread = None
        self.running = False
        self.ocr_warmup_complete = False
        self.ocr_warmup_error: str | None = None
        self.ocr_warmup_report: dict[str, object] = {}
        self.ocr_warmup_stage = "Подготовка распознавания"
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
        self._last_status_write = 0.0
        self._last_transition = None
        self._closed_window_width = 1100

        self.root.title("Kingdom Guard Prize Monitor | Рабочая версия")
        self.root.geometry("1100x980")
        self.root.minsize(1100, 980)

        self.connection_var = tk.StringVar(value="Проверка...")
        self.window_label_var = tk.StringVar(value=self._selected_window.name if self._selected_window else 'MEmu')
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
        self.test_range_min_var = tk.StringVar(value=f"{self.monitor.user_range.test_min_prize:,}".replace(",", " "))
        self.test_range_max_var = tk.StringVar(value=f"{self.monitor.user_range.test_max_prize:,}".replace(",", " "))
        self.log_toggle_var = tk.StringVar(value="Показать логи")
        self.no_upper_var = tk.BooleanVar(value=self.monitor.user_range.no_upper_limit)
        self.start_method_var = tk.StringVar(value=self.monitor.user_range.start_method)
        self.start_percent_var = tk.StringVar(value=str(self.monitor.user_range.start_percent))
        self.gem_limit_enabled_var = tk.BooleanVar(value=self.monitor.user_range.minimum_gems is not None)
        self.gem_floor_var = tk.StringVar(value=f"{self.monitor.user_range.minimum_gems if self.monitor.user_range.minimum_gems is not None else 40000:,}".replace(',',' '))
        self.gem_balance_var = tk.StringVar(value="Баланс: проверяем")
        if self._selected_windows:
            self._install_group(self._selected_windows, self.monitor)

        self._build()
        if profile != 'default':
            from app.version import APP_VERSION
            self.root.title(f'Фонтан {APP_VERSION} — отдельный фонд ' + profile)
        self._bind_hotkeys()
        self._connect()
        self._refresh_static_panels()
        self._start_ocr_warmup()
        self.root.after(100, self._collect_group)

    def _build(self) -> None:
        from app.ui_design import FountainDesign
        self.design = FountainDesign(self)

    def _bind_hotkeys(self) -> None:
        self.root.bind("<Control-o>", lambda _event: self.choose_window())
        self.root.bind("<F8>", lambda _event: self.toggle())
        self.root.bind("<F9>", lambda _event: self.emergency_stop())

    def _sync_mode(self) -> None:
        if self._switching_window or self._window_picker_active or self._selection_error:
            self.mode_var.set(False)
            return
        enabled = self.mode_var.get()
        if enabled:
            active_range = self.monitor.target_range_label()
            approved = messagebox.askyesno(
                "Подтверждение реального режима",
                "Будет включён реальный режим.\n"
                + ("Окна: " + ', '.join(s.window.name for s in self._group.sessions.values()) + ".\n"
                   if self._group else "")
                +
                f"Активный диапазон: {active_range}.\n"
                "Диапазон запускает серию; рост выше максимума не останавливает её.\n"
                "При обнулении клики прекращаются. При долгой потере цифр серия ждёт.\n"
                + (f"Предел одной серии: {self.config.continuous_max_taps} желаний.\n" if self.config.continuous_max_taps else
                 "Серия без числового лимита: до падения фонда или защитной остановки.\n")
                + "Каждое желание расходует 100 самоцветов. F9 — остановка.\n"
                + (f"Сохранить на счёте не меньше {self.monitor.user_range.minimum_gems:,} самоцветов.\n".replace(',',' ')
                   if self.monitor.user_range.minimum_gems is not None else "Ограничение остатка самоцветов не включено.\n")
                + "Продолжить?",
                icon="warning",
            )
            if not approved:
                self.mode_var.set(False)
                enabled = False
        _changed, message = (self._group.set_real_mode(enabled) if self._group else self.monitor.set_real_mode(enabled))
        self.mode_var.set(self._group.any_real if self._group else self.monitor.state.real_mode_armed)
        self.mode_label_var.set("Реальный режим" if self.monitor.state.real_mode_armed else "Тестовый режим")
        self.mode_banner_var.set(self.monitor.mode_banner())
        self.range_var.set(f"Диапазон: {self.monitor.target_range_label()}")
        self.active_range_var.set(self.monitor.target_range_label())
        self.tap_policy_var.set(self.monitor.real_taps_label())
        if message:
            self._append_log(message)
        if enabled and not _changed:
            messagebox.showwarning("Режим не включён", message)
        if enabled and _changed:
            self.start()
        elif self.running:
            self.monitor.resume()

    def on_start_method_changed(self) -> None:
        if getattr(self, '_confirming_start_method', False) or not self.mode_var.get():
            return
        previous = self.monitor.user_range.start_method
        if self.start_method_var.get() == previous:
            return
        self._confirming_start_method = True
        try:
            if not self.apply_range():
                self.start_method_var.set(previous)
        finally:
            self._confirming_start_method = False

    def apply_range(self) -> bool:
        try:
            min_value = int(self.test_range_min_var.get().replace(" ", "").strip())
            max_value = int(self.test_range_max_var.get().replace(" ", "").strip())
            gem_floor = int(self.gem_floor_var.get().replace(" ", "").strip()) if self.gem_limit_enabled_var.get() else None
            start_percent = int(self.start_percent_var.get().strip())
        except ValueError:
            messagebox.showerror("Ошибка настроек", "Значения фонда, процент и остаток самоцветов должны быть целыми числами.")
            return False

        if self.mode_var.get():
            range_text = (f"{start_percent}% от фонда перед последним обнулением" if self.start_method_var.get() == 'percent'
                          else f"от {min_value:,}, без верхнего предела" if self.no_upper_var.get()
                          else f"{min_value:,} - {max_value:,}")
            approved = messagebox.askyesno(
                "Перейти на новое правило кликов?",
                "Сейчас включены настоящие клики.\n"
                f"Новое правило: {range_text}.\n".replace(',',' ')
                + (f"Оставить на счёте не меньше {gem_floor:,} самоцветов.\n".replace(',',' ') if gem_floor is not None else "Ограничение остатка выключено.\n")
                +
                "После подтверждения настройки будут сохранены.\n"
                "Клики продолжатся только при выполнении нового правила.\n"
                "Применить эти настройки?",
                icon="warning",
            )
            if not approved:
                return False

        ok, message = self.monitor.update_test_range(min_value, max_value,
            no_upper_limit=self.no_upper_var.get(), minimum_gems=gem_floor, update_gem_limit=True,
            start_method=self.start_method_var.get(), start_percent=start_percent)
        if not ok:
            messagebox.showerror("Ошибка диапазона", message)
            return False
        if self._group:
            self._group.update_settings(self.monitor.user_range)

        self.range_var.set(f"Диапазон: {self.monitor.target_range_label()}")
        self.active_range_var.set(self.monitor.target_range_label())
        self._append_log(message)
        if hasattr(self, 'design'):
            self.design.mark_saved()
        return True

    def _connect(self) -> None:
        if self._selection_error:
            self.connection_var.set(self._selection_error)
            return
        ok, message = self.monitor.connect()
        self.connection_var.set("Подключено" if ok else f"Ошибка: {message}")
        self._append_log(message)

    def choose_window(self) -> None:
        if self._switching_window or self._window_picker_active:
            return
        self._window_picker_active = True
        from app.window_picker import WindowPicker
        serials = [s.window.serial for s in self._group.sessions.values()] if self._group else [self.config.adb_serial]
        picker = WindowPicker(self.root, self._base_config.adb_path, serials, self._select_windows)
        def dismissed(event):
            if event.widget is picker:
                self._window_picker_active = False
        picker.bind('<Destroy>', dismissed)

    def open_program_window(self) -> None:
        profile = uuid.uuid4().hex
        try:
            subprocess.Popen([sys.executable, '-m', 'app.ui', '--profile', profile],
                             cwd=str(Path(__file__).resolve().parents[1]),
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            messagebox.showerror('Не удалось открыть окно', str(exc), parent=self.root)

    def _select_windows(self, windows) -> None:
        current = {(w.uuid, w.serial) for w in self._selected_windows}
        selected = {(w.uuid, w.serial) for w in windows}
        if current == selected:
            return
        self._switching_window = True
        self._warmup_start_requested = False
        self.pause()
        self.status_var.set('Переключаем окно. Платные клики выключены…')
        def wait_for_poll():
            if getattr(self, '_window_close_started', False):
                return
            if ((self._poll_thread is not None and self._poll_thread.is_alive())
                    or (self._warmup_thread is not None and self._warmup_thread.is_alive())
                    or (self._cleanup_thread is not None and self._cleanup_thread.is_alive())):
                self.root.after(30, wait_for_poll)
                return
            self._cleanup_thread = threading.Thread(target=self._close_monitors, name='kgpm-window-switch', daemon=True)
            self._cleanup_thread.start()
            self.root.after(30, finish)
        def finish():
            if getattr(self, '_window_close_started', False):
                return
            if self._cleanup_thread.is_alive():
                self.root.after(30, finish)
                return
            from app.memu_windows import config_for_window, discover_windows, save_selections
            try:
                self._device_leases.release()
                available = {w.uuid: w for w in discover_windows(self._base_config.adb_path)}
                if any(w.uuid not in available for w in windows):
                    raise RuntimeError('Одно из выбранных окон уже закрыто. Проверьте список окон.')
                fresh = [available[w.uuid] for w in windows]
                self._device_leases.acquire([identity for w in fresh for identity in (w.serial, 'device:' + w.uuid)])
                self.config = config_for_window(self._base_config, fresh[0])
                self.monitor = PrizeMonitor(self.config)
                self._install_group(fresh, self.monitor)
                self._selection_error = ''
                self.window_label_var.set(fresh[0].name)
                save_selections(self._selection_path, fresh)
                self._update_group_table()
                self._connect()
                self._refresh_runtime_panels()
                self._refresh_static_panels()
                self.ocr_warmup_complete = False
                self.ocr_warmup_error = None
                self._start_ocr_warmup()
                self._write_runtime_status()
                self._append_log('Выбраны окна: ' + ', '.join(w.name for w in fresh) + '. Нажмите «Начать» для всех выбранных окон.')
            except Exception as exc:
                self._device_leases.release()
                self._selection_error = str(exc)
                self.status_var.set(str(exc))
                messagebox.showerror('Выбор окна', str(exc), parent=self.root)
            finally:
                self._switching_window = False
        wait_for_poll()

    def _install_group(self, windows, primary):
        from app.memu_windows import config_for_window
        from app.monitor_group import MonitorGroup
        entries = [(windows[0], primary)]
        entries.extend((w, PrizeMonitor(config_for_window(self._base_config, w))) for w in windows[1:])
        self._group = MonitorGroup(entries)
        self._selected_windows = windows
        self._selected_window = windows[0]
        self._focus_uuid = windows[0].uuid
        self._session_snapshots.clear()
        self._session_statuses.clear()

    def _close_monitors(self):
        if self._group:
            self._group.close()
        else:
            self.monitor.close()

    def _focus_session(self, _event=None):
        if self._group is None or self._switching_window:
            return
        index = self.group_picker.current()
        selected = [self._group_picker_ids[index]] if 0 <= index < len(self._group_picker_ids) else []
        if not selected or selected[0] not in self._group.sessions:
            return
        session = self._group.sessions[selected[0]]
        self._focus_uuid = selected[0]
        self.monitor = session.monitor
        self.config = session.monitor.config
        self.window_label_var.set(session.window.name)
        self._last_transition = None
        snapshot = self._session_snapshots.get(selected[0])
        if snapshot:
            self._apply_snapshot(snapshot)
        else:
            self._refresh_runtime_panels()
            self._refresh_static_panels()
        self.mode_var.set(self._group.any_real)

    def _update_group_table(self):
        if not hasattr(self, 'group_picker'):
            return
        sessions = self._group.sessions if self._group else {}
        self._group_picker_ids = list(sessions)
        self.group_picker.configure(values=[s.window.name for s in sessions.values()])
        if self._focus_uuid in self._group_picker_ids:
            self.group_picker.current(self._group_picker_ids.index(self._focus_uuid))
        if sessions:
            self.group_frame.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(4,0))
        else:
            self.group_frame.grid_remove()

    def _collect_group(self):
        if self._group and not self._switching_window:
            import queue
            for _ in range(128):
                try:
                    uuid, kind, payload = self._group.events.get_nowait()
                except queue.Empty:
                    break
                if kind == 'snapshot':
                    self._session_snapshots[uuid] = payload
                    self._session_statuses.pop(uuid, None)
                    if uuid == self._focus_uuid and self._group.sessions[uuid].active.is_set():
                        self._apply_snapshot(payload)
                    elif uuid != self._focus_uuid:
                        for event in payload.tap_events:
                            self._append_log(f'[{self._group.sessions[uuid].window.name}] {event}')
                else:
                    self._session_statuses[uuid] = ('Ошибка подключения: ' if kind == 'error' else '') + payload
                    if kind == 'reset':
                        self._session_snapshots.pop(uuid, None)
                        if uuid == self._focus_uuid:
                            self._refresh_runtime_panels()
                            self._refresh_static_panels()
                    if kind == 'error':
                        self._append_log(f'[{self._group.sessions[uuid].window.name}] {payload}')
            self.running = self._group.any_active
            self.mode_var.set(self._group.any_real)
            self._update_group_table()
            if time.monotonic()-self._last_status_write > 1:
                self._last_status_write = time.monotonic()
                self._write_runtime_status()
        self.root.after(100, self._collect_group)

    def _append_log(self, text: str) -> None:
        timestamp = self.monitor.timestamp()
        self.log_panel.append(f"[{timestamp}] {text}\n")

    def toggle_logs(self) -> None:
        self.root.update_idletasks()
        if self.logs_visible:
            self.paned.forget(self.log_panel)
            self.logs_visible = False
            self.log_toggle_var.set("Показать логи")
            self.root.minsize(840, 760)
            self.root.geometry(f"{self._closed_window_width}x{self.root.winfo_height()}")
            return

        self._closed_window_width = max(840, self.root.winfo_width())
        self.paned.add(self.log_panel, weight=0)
        self.logs_visible = True
        self.log_toggle_var.set("Скрыть логи")
        target_width = self._closed_window_width + 380
        self.root.minsize(1220, 760)
        self.root.geometry(f"{target_width}x{self.root.winfo_height()}")
        self.root.update_idletasks()
        try:
            self.paned.sashpos(0, self._closed_window_width)
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
            self.history_table.insert("", "end", iid="placeholder", values=("", "", "", ""))
            if hasattr(self,'design'):
                self.design.update_empty_history()
            return
        for index, row in enumerate(rows):
            row = list(row)
            if str(row[2]).isdigit():
                row[2] = f"{int(row[2]):,}".replace(",", " ")
            if index == 0 and hasattr(self, 'design'):
                row[1] = f"●  {row[1]}"
            self.history_table.insert("", "end", iid=f"event-{index}", values=row,
                                      tags=("newest",) if index == 0 else ())
        if hasattr(self,'design'):
            self.design.update_empty_history()

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
        self.mode_var.set(self._group.any_real if self._group else self.monitor.state.real_mode_armed)
        self.mode_label_var.set("Реальный режим" if self.monitor.state.real_mode_armed else "Тестовый режим")
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
        self.reset_since_var.set('' if self.monitor.state.manual_reset_block_real_taps else
                                 self.monitor._history_since_reset_label(now))
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
        self.total_taps_var.set(f"{self.monitor.state.real_taps} / {self.monitor.state.virtual_taps}")
        self.mode_banner_var.set(self.monitor.mode_banner())
        self.range_var.set(f"Диапазон: {self.monitor.target_range_label()}")
        if self.monitor.state.test_mode:
            self.active_range_var.set(self.monitor.editable_test_range_label())
        else:
            self.active_range_var.set(self.monitor.target_range_label())
        self.tap_policy_var.set(self.monitor.real_taps_label())

    def _apply_snapshot(self, snapshot: PollSnapshot) -> None:
        self.mode_var.set(self._group.any_real if self._group else self.monitor.state.real_mode_armed)
        self.value_var.set(f"{snapshot.value:,}".replace(",", " ") if snapshot.value is not None else "—")
        transition = (snapshot.phase.value, snapshot.notification_veto, snapshot.event_screen_ok,
                      snapshot.button_visible, snapshot.in_range, self.monitor.state.real_mode_armed)
        if transition != self._last_transition:
            self._last_transition = transition
            with (self.monitor.config.runtime_dir/'monitor_events.jsonl').open('a', encoding='utf-8') as log:
                log.write(json.dumps(dict(timestamp=datetime.now().astimezone().isoformat(),
                          phase=snapshot.phase.value, value=snapshot.trusted_value, status=snapshot.status,
                          screen_ok=snapshot.event_screen_ok, button_ok=snapshot.button_visible,
                          notification=snapshot.notification_veto, real_mode=self.monitor.state.real_mode_armed,
                          real_taps=self.monitor.state.real_taps), ensure_ascii=False) + '\n')
        if time.monotonic() - self._last_status_write > 1:
            self._last_status_write = time.monotonic()
            self._write_runtime_status()
        self.ocr_var.set(self._user_visible_ocr_text(snapshot))
        reason = snapshot.status
        if snapshot.recognition.method == "popup":
            reason = "Мешающее окно: закрываем крестиком и ждём экран желаний."
        elif snapshot.phase == MonitorPhase.ACTIVE_CLICKING and self.config.continuous_clicking:
            reason = snapshot.status
        elif snapshot.notification_veto:
            reason = "Ждём окончания уведомления. Продолжим автоматически после подтверждения цифр."
        elif not snapshot.event_screen_ok or not snapshot.button_visible:
            reason = "Откройте экран желания. Нужны надписи фонда, счётчика и кнопки. Проверьте разрешение MEmu: 1080 × 1080."
        elif snapshot.trusted_value is None:
            reason = "Ждём, пока цифры станут видны. Продолжим автоматически после подтверждения."
        elif snapshot.phase == MonitorPhase.RESET_COOLDOWN:
            reason = f"После обнуления: осталось {snapshot.cooldown_remaining} сек. Затем продолжим автоматически."
        elif snapshot.phase == MonitorPhase.RESET_TIME_UNKNOWN:
            reason = "Первые 120 секунд наблюдаем после перерыва. Затем работа начнётся автоматически."
        elif not snapshot.in_range:
            reason = f"Ждём входа фонда в диапазон {snapshot.target_range_label}."
        elif snapshot.phase == MonitorPhase.WAITING or snapshot.phase == MonitorPhase.CANDIDATE:
            reason = "Фонд в диапазоне. Подтверждаем по новым кадрам."
        elif snapshot.phase == MonitorPhase.CHECKING_AFTER_BURST:
            reason = "Проверяем фонд после серии. Окно остаётся открытым."
        if snapshot.status.startswith("С кликами выключено:"):
            reason = snapshot.status
        self.status_var.set(reason)
        self.phase_var.set(snapshot.phase.value)
        self.confirmations_var.set(str(snapshot.confirmation_hits))
        self.screen_var.set(
            f"{'подтверждён' if snapshot.event_screen_ok else 'подтверждён для серии' if snapshot.continuation_screen_ok else 'не подтверждён'} "
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
        self.total_taps_var.set(f"{self.monitor.state.real_taps} / {self.monitor.state.virtual_taps}")
        self.mode_banner_var.set(snapshot.mode_banner)
        self.range_var.set(f"Диапазон: {snapshot.target_range_label}")
        if self.monitor.state.test_mode:
            self.active_range_var.set(snapshot.editable_test_range_label)
        else:
            self.active_range_var.set(snapshot.target_range_label)
        self.tap_policy_var.set(snapshot.real_taps_label)
        self.reset_since_var.set('' if self.monitor.state.manual_reset_block_real_taps else
                                 snapshot.reset_since_history_label)
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
        if self._switching_window or self._window_picker_active or self._selection_error or getattr(self, '_window_close_started', False):
            self.status_var.set(self._selection_error or 'Сначала завершите выбор окна MEmu.')
            return
        if self.running:
            if self._group:
                self._group.start()
            return
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            self.root.after(100,self.start)
            return
        if not self.ocr_warmup_complete:
            self._warmup_start_requested = True
            warmup_thread = getattr(self, '_warmup_thread', None)
            if getattr(self, 'ocr_warmup_error', None) and not (warmup_thread and warmup_thread.is_alive()):
                self._start_ocr_warmup()
            self.status_var.set("Готовим программу. Наблюдение начнётся автоматически после подготовки.")
            return
        if self._group:
            self._group.start()
            self.running = True
            self.status_var.set(f'Наблюдение запущено: {len(self._group.sessions)} окна. Получаем свежие значения…')
            self._append_log('Наблюдение запущено во всех выбранных окнах')
            self._write_runtime_status()
            return
        if self.config.stream_transport_enabled and self.monitor._stream is None:
            ok,message=self.monitor.connect()
            self.connection_var.set(message)
            if not ok:
                self.status_var.set(message)
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
        config, monitor = self.config, self.monitor
        self.ocr_warmup_complete = False
        self.ocr_warmup_error = None
        self.ocr_warmup_report = {}
        self.ocr_warmup_stage = 'Загружаем распознавание'

        def worker() -> None:
            diagnostic = None
            try:
                # Optional diagnostics must never prevent OCR from starting.
                try:
                    config.runtime_dir.mkdir(parents=True, exist_ok=True)
                    diagnostic = (config.runtime_dir / 'startup_warmup.log').open('a', encoding='utf-8')
                    faulthandler.dump_traceback_later(20, file=diagnostic)
                except OSError:
                    if diagnostic is not None:
                        diagnostic.close()
                    diagnostic = None
                crop_path = config.prize_crop_path
                if crop_path.exists():
                    with Image.open(crop_path) as source:
                        crop = source.convert("RGB")
                    warmup_source = str(crop_path.resolve())
                else:
                    crop = Image.new("RGB", (config.prize_crop.width, config.prize_crop.height), (80, 80, 80))
                    warmup_source = "synthetic_read_only_crop"
                report = monitor._ocr_pipeline.engines.warm_up(crop)
                import paddleocr
                import rapidocr

                report.update(
                    {
                        "python": sys.executable,
                        "rapidocr_module": str(getattr(rapidocr, "__file__", "")),
                        "paddleocr_module": str(getattr(paddleocr, "__file__", "")),
                        "pipeline": type(monitor._ocr_pipeline).__name__,
                        "crop_path": warmup_source,
                    }
                )
                self.ocr_warmup_report = report
            except Exception as exc:
                self.ocr_warmup_error = f"{type(exc).__name__}: {exc}"
            finally:
                if diagnostic is not None:
                    faulthandler.cancel_dump_traceback_later()
                    diagnostic.close()

        self._warmup_thread = threading.Thread(target=worker, name="kgpm-ocr-warmup", daemon=True)
        self._warmup_thread.start()
        self.root.after(100, self._poll_ocr_warmup)

    def _poll_ocr_warmup(self) -> None:
        if self._warmup_thread is not None and self._warmup_thread.is_alive():
            self.status_var.set(self.ocr_warmup_stage)
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
        path = getattr(self, '_base_config', self.config).runtime_dir / "gui_runtime_status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "selected_window": self.window_label_var.get(),
            "adb_serial": self.config.adb_serial,
            "python": sys.executable,
            "title": self.root.title(),
            "hwnd": int(self.root.winfo_id()),
            "viewable": bool(self.root.winfo_viewable()),
            "geometry": self.root.geometry(),
            "ocr_warmup_complete": self.ocr_warmup_complete,
            "ocr_warmup_error": self.ocr_warmup_error,
            "ocr_warmup": self.ocr_warmup_report,
            "ocr_warmup_stage": getattr(self, 'ocr_warmup_stage', ''),
            "ocr_warmup_thread_alive": bool(self._warmup_thread and self._warmup_thread.is_alive()),
            "test_mode": self.monitor.state.test_mode,
            "real_mode_armed": self.monitor.state.real_mode_armed,
            "tap_decisions_enabled": self.monitor.tap_decisions_enabled,
            "project_root": str(Path.cwd()),
            "profile": getattr(self, 'profile', 'default'),
            "running": self.running,
            "global_f8": getattr(self, 'global_f8', False),
            "global_f9": getattr(self, 'global_f9', False),
            "phase": self.monitor.state.phase.value,
            "trusted_value": self.monitor.state.trusted_value,
            "real_taps": self.monitor.state.real_taps,
            "virtual_taps": self.monitor.state.virtual_taps,
            "range": self.monitor.target_range_for_mode(),
            "status": self.monitor.state.last_status,
            "windows": [{"name": s.window.name, "serial": s.window.serial,
                         "running": s.active.is_set(), "real_mode_armed": s.monitor.state.real_mode_armed,
                         "value": s.monitor.state.last_value, "phase": s.monitor.state.phase.value,
                         "real_taps": s.monitor.state.real_taps, "virtual_taps": s.monitor.state.virtual_taps,
                         "worker_alive": bool(s.thread and s.thread.is_alive()),
                         "status": s.monitor.state.last_status,
                         "last_error": s.last_error,
                         "fund_source": s.fund_source}
                        for s in self._group.sessions.values()] if self._group else [],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def pause(self) -> None:
        self.running = False
        if self._group:
            self._group.pause()
        else:
            self.monitor.pause()
            self.monitor.adb.close_shell()
        self._refresh_static_panels()
        self.status_var.set(self.monitor.state.last_status)
        self.phase_var.set(self.monitor.state.phase.value)
        self._append_log(self.monitor.state.last_status)
        self._write_runtime_status()

    def reset_lock(self) -> None:
        approved = messagebox.askyesno(
            'Ждать новое обнуление',
            'Начать новый период наблюдения для всех выбранных окон?\n\n'
            'Текущие показания и таймер будут сброшены. Кликов не будет до нового '
            'обнуления и окончания двухминутного ожидания.\n\n'
            'История и сохранённые настройки останутся. Эта кнопка не обнуляет фонд в игре.',
            icon='question',
        )
        if not approved:
            return
        self.reset_since_var.set('')
        self.mode_var.set(False)
        if self._group:
            self._session_snapshots.clear()
            self._group.reset_cycle()
            self.status_var.set('Сбрасываем текущий период во всех выбранных окнах…')
            self._append_log('Ждём новое обнуление во всех выбранных окнах. История сохранена.')
            return
        self.monitor.set_real_mode(False)
        self.monitor.reset_lock()
        self.monitor.state.reset_time_known = False
        self.monitor.state.manual_reset_block_real_taps = True
        self.monitor.state.unknown_since = self.monitor._now()
        self.monitor.state.phase = MonitorPhase.RESET_TIME_UNKNOWN
        self.monitor.state.last_status = 'Ждём новое обнуление. История сохранена, клики выключены.'
        self.monitor._save_persisted_state()
        self._refresh_runtime_panels()
        self._refresh_static_panels()
        self._append_log(self.monitor.state.last_status)

    def emergency_stop(self) -> None:
        self.running = False
        self._warmup_start_requested = False
        self.mode_var.set(False)
        if self._group:
            self._group.emergency_stop()
        else:
            self.monitor.emergency_stop()
        if self._cleanup_thread is None or not self._cleanup_thread.is_alive():
            self._cleanup_thread=threading.Thread(target=self._close_monitors,name='kgpm-cleanup',daemon=True)
            self._cleanup_thread.start()
        self.monitor.state.last_status = "Аварийная остановка (F9). Реальный режим выключен."
        self._refresh_static_panels()
        self._write_runtime_status()
        self.status_var.set(self.monitor.state.last_status)
        self.phase_var.set(self.monitor.state.phase.value)
        self._append_log("Аварийная остановка (F9)")

    def _schedule_tick(self) -> None:
        if not self.running:
            return
        if self._poll_thread is not None:
            return
        self._poll_result = self._poll_error = None
        def worker() -> None:
            try:
                self._poll_result = self.monitor.poll_once()
            except Exception as exc:
                self._poll_error = exc
        self._poll_thread = threading.Thread(target=worker,name='kgpm-monitor-poll',daemon=True)
        self._poll_thread.start()
        self.root.after(10,self._collect_poll)

    def _collect_poll(self) -> None:
        if self._poll_thread is not None and self._poll_thread.is_alive():
            self.root.after(10,self._collect_poll)
            return
        self._poll_thread = None
        if not self.running:
            if self.monitor.state.phase != MonitorPhase.EMERGENCY_STOP:
                self.monitor.pause()
            return
        if self._poll_error is not None:
            if isinstance(self._poll_error,FreshFrameUnavailable):
                self.monitor.state.next_click_at=None
                self.status_var.set("Нажатия приостановлены: восстанавливается свежий видеопоток")
                self.root.after(100,self._schedule_tick)
                return
            self.pause()
            self.status_var.set("Ошибка мониторинга")
            self._append_log(f"Ошибка: {self._poll_error}")
            messagebox.showerror("Мониторинг приостановлен", str(self._poll_error))
            return
        snapshot = self._poll_result
        if snapshot is None:
            return
        self._apply_snapshot(snapshot)
        if snapshot.phase in {MonitorPhase.PAUSED, MonitorPhase.EMERGENCY_STOP}:
            self.running = False
            self._refresh_static_panels()
        if self.running:
            self.root.after(poll_delay_ms(snapshot.phase,self.config.poll_interval_ms,
                                         getattr(self.monitor.state, 'fast_observation_active', False)),self._schedule_tick)


def main() -> None:
    from app.profiles import profile_config, profile_mutex
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', default='default')
    args = parser.parse_args()
    config = profile_config(AppConfig(), args.profile)
    manager = SingleInstanceManager(config.instance_state_path, profile_mutex(args.profile))
    manager = _start_or_focus_existing_instance(config, manager)
    if manager is None:
        return

    root = tk.Tk()
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Segoe UI", 10), background="#f5f2e9", foreground="#263d39")
    style.configure("TFrame", background="#f5f2e9")
    style.configure("TLabel", background="#f5f2e9")
    style.configure("TLabelframe", background="#f5f2e9", bordercolor="#cdd5cb")
    style.configure("TLabelframe.Label", foreground="#126a5b", font=("Segoe UI", 10, "bold"))
    style.configure("Brand.TLabel", foreground="#126a5b", font=("Segoe UI", 10, "bold"))
    style.configure("Heading.TLabel", font=("Segoe UI", 23, "bold"))
    style.configure("Fund.TLabel", foreground="#126a5b", font=("Segoe UI", 22, "bold"))
    style.configure("Hint.TLabel", foreground="#63716b", font=("Segoe UI", 9))
    style.configure("TButton", padding=(10, 7))
    style.configure("Accent.TButton", background="#126a5b", foreground="white")
    style.map("Accent.TButton", background=[("active", "#218672")])
    style.configure("Treeview", background="#fffdf6", fieldbackground="#fffdf6", rowheight=25)
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    app = AppWindow(root, config, args.profile)
    from app.hotkeys import SharedHotkeys
    hotkeys = SharedHotkeys(root, app.toggle, app.emergency_stop, AppConfig().runtime_dir / 'hotkey_commands')
    app.global_f8 = hotkeys.keys[0].registered
    app.global_f9 = hotkeys.keys[1].registered
    app._append_log('F8 запускает и приостанавливает все окна программы; F9 останавливает все окна. '
                    'Если клавиша занята посторонней программой, используйте кнопки в окне.')
    root.deiconify()
    root.update_idletasks()
    root.update()
    root.lift()
    manager.register_window(root.winfo_id(), root.title())
    app._write_runtime_status()

    def on_close() -> None:
        app.running = False
        if app._group:
            app._group.pause()
        app.monitor._tap_cancel.set()
        if app._poll_thread is not None and app._poll_thread.is_alive():
            root.after(20,on_close)
            return
        if app._cleanup_thread is None or not app._cleanup_thread.is_alive():
            if getattr(app,'_window_close_started',False):
                app._device_leases.release()
                manager.release()
                root.destroy()
                return
            app._window_close_started=True
            hotkeys.close()
            app._cleanup_thread=threading.Thread(target=app._close_monitors,name='kgpm-cleanup',daemon=True)
            app._cleanup_thread.start()
        app.status_var.set("Завершение записи диагностики. Настоящие нажатия выключены.")
        root.after(20,on_close)

    app.close_callback = on_close
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
