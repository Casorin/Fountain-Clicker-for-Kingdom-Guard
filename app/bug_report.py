"""Previewed, allowlisted diagnostics for a user-submitted support form."""
import json
import platform
import hashlib
import queue
import re
import threading
import webbrowser
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from app.version import APP_VERSION
from pathlib import Path
from urllib.parse import urlencode, urlparse
import tkinter as tk
from tkinter import messagebox, ttk
from PIL import Image, ImageDraw, ImageTk
from app.window_picker import PinkScrollbar

FORM_CONFIG = Path(__file__).resolve().parent.parent / 'assets' / 'support_form.json'


def report_monitors(app):
    group = getattr(app, '_group', None)
    sessions = list(group.sessions.values()) if group else []
    return [(session.window.provider, session.monitor, session.window.uuid) for session in sessions] or [('не определён', app.monitor, 'primary')]


def read_display_sizes(monitors):
    sizes = {}
    for _provider, monitor, identifier in monitors:
        try:
            adb = monitor.adb
            output = adb._run('-s', adb.serial, 'shell', 'wm', 'size', timeout=2).stdout.decode('utf-8', errors='replace')
            matches = re.findall(r'(?:Physical|Override) size:\s*(\d+)x(\d+)', output)
            sizes[identifier] = tuple(map(int, matches[-1])) if matches else None
        except Exception:
            sizes[identifier] = None
    return sizes


def size_label(size):
    return f'{size[0]} × {size[1]}' if size and len(size) == 2 and min(size) > 0 else 'ещё не получен'


def build_report(app, display_sizes=None):
    monitor = app.monitor
    state = monitor.state
    config = monitor.config
    lines = ['Фонтан — диагностика', 'Версия: ' + APP_VERSION,
             'Время UTC: ' + datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'Windows: ' + platform.release(), 'Python: ' + platform.python_version(),
             'Состояние: ' + state.phase.value,
             'Режим: ' + ('с кликами' if state.real_mode_armed else 'без кликов'),
             'Наблюдение: ' + ('включено' if app.running else 'остановлено')]
    digest = hashlib.sha256()
    for name in ('ui.py', 'monitor.py', 'production_ocr.py', 'bug_report.py'):
        digest.update((Path(__file__).parent/name).read_bytes())
    lines.append('Идентификатор сборки: ' + digest.hexdigest()[:16])
    for package in ('rapidocr', 'paddleocr', 'onnxruntime', 'av'):
        try:
            lines.append(package + ': ' + version(package))
        except PackageNotFoundError:
            lines.append(package + ': не установлено')
    monitors = report_monitors(app)
    previews = getattr(app, '_window_preview_diagnostics', [])
    if previews:
        lines.append('Последняя проверка снимков при выборе окон:')
        for index, (provider, result) in enumerate(previews[:100], 1):
            lines.append(f'  Проверка {index} ({provider}): {result}')
    lines.append('Количество выбранных окон: ' + str(len(monitors)))
    for index, (provider, current, identifier) in enumerate(monitors, 1):
        if provider not in {'MEmu', 'LDPlayer', 'BlueStacks'}:
            provider = 'не определён'
        lines.append(f'Окно {index}: {provider}; состояние {current.state.phase.value}')
        stream = getattr(current, '_stream', None)
        wallet = getattr(current, 'gem_guard', None)
        if wallet is not None and getattr(wallet, 'read_ms', None) is not None:
            lines.append(f'  Проверка баланса в фоне, мс: {wallet.read_ms:.1f}')
        session = getattr(getattr(app, '_group', None), 'sessions', {}).get(identifier)
        if session is not None and hasattr(session, 'active'):
            lines += [f'  Наблюдение окна: {session.active.is_set()}; поток: {bool(session.thread and session.thread.is_alive())}',
                      '  Фонд: ' + ('источник общего фонда' if getattr(session, 'fund_source', False)
                                   else 'из общего источника' if getattr(session, 'shared_fund', None) else 'отдельное чтение')]
            lines.append(f'  Ожидания картинки / фонда: {getattr(session,"frame_waits",0)} / {getattr(session,"fund_waits",0)}')
            if getattr(session, 'poll_ms', None) is not None:
                lines.append(f'  Обработка окна, мс: {session.poll_ms:.1f}')
            if getattr(session, 'last_wait_reason', None):
                lines.append('  Сейчас ждём: ' + session.last_wait_reason)
            if getattr(session, 'last_error', None):
                # Raw exceptions may contain device addresses or local paths.
                error = session.last_error.lower()
                category = ('видеопоток / подключение' if any(x in error for x in ('stream', 'video', 'connect', 'виде', 'подключ'))
                            else 'время ожидания' if any(x in error for x in ('timeout', 'timed out'))
                            else 'внутренняя ошибка обработки')
                lines.append('  Причина остановки: ' + category)
        screen = getattr(current, '_latest_native_screen', None)
        frame_size = getattr(screen, 'size', None) or getattr(stream, 'size', None)
        display_size = (display_sizes or {}).get(identifier)
        lines += ['  Android-экран: ' + (size_label(display_size) if display_size else 'не удалось определить' if display_sizes is not None else 'проверяем…'),
                  '  Видеокадр: ' + size_label(frame_size),
                  '  Реальный режим разрешён: ' + str(current.state.real_mode_armed),
                  '  Уведомление перекрывает фонд: ' + str(current.state.notification_veto)]
        snapshots = getattr(app, '_session_snapshots', {})
        snapshot = snapshots.get(identifier)
        if snapshot is not None:
            lines += [f'  Последнее наблюдение: {snapshot.timestamp}',
                      f'  Экран / кнопка: {snapshot.event_screen_ok} / {snapshot.button_visible}',
                      f'  OCR: {snapshot.ocr_status.value}',
                      f'  Получение кадра, мс: {snapshot.capture_ms:.1f}',
                      f'  Распознавание, мс: {snapshot.authoritative_ocr_ms}',
                      f'  Осталось ожидания после обнуления, с: {snapshot.cooldown_remaining}']
        else:
            lines.append('  Свежих наблюдений в этом запуске ещё нет.')
        writer = getattr(current, '_diagnostics_writer', None)
        if writer is not None:
            lines.append(f'  Очередь диагностики: {writer.pending_count}; поток работает: {writer.is_alive}')
    lines += ['Интервал наблюдения, мс: ' + str(config.poll_interval_ms),
              'Видео: ' + ('включено' if config.stream_transport_enabled else 'выключено'),
              'Личные данные, адреса подключения, пути, игровые балансы и сырые логи исключены.']
    log = getattr(app, 'log', None)
    text = log.get('1.0', 'end')[-12000:] if log is not None else ''
    # Export error categories, never arbitrary log strings or account identifiers.
    categories = [('Недостаток памяти', ('Недостаточно памяти', 'HostMemoryLow', '0xc000012d')),
                  ('Нет свежего изображения', ('fresh', 'свежий видеокадр')),
                  ('Время ожидания истекло', ('timeout', 'timed out')),
                  ('Ошибка видеопотока', ('Видеопоток', 'video disconnected', 'Video stream closed')),
                  ('Ошибка подключения', ('Ошибка подключения', 'connection timed out'))]
    lines.append('Сводка последних сообщений:')
    found = False
    for label, markers in categories:
        count = sum(any(marker.lower() in line.lower() for marker in markers) for line in text.splitlines())
        if count:
            found = True
            lines.append(label + ': ' + str(count))
    if not found:
        lines.append('Известные категории ошибок не обнаружены.')
    return '\n'.join(lines)


def form_url(report, path=FORM_CONFIG):
    data = json.loads(path.read_text(encoding='utf-8'))
    url = data['url']
    parsed = urlparse(url)
    field = data['diagnostics_field']
    if parsed.scheme != 'https' or parsed.netloc != 'docs.google.com' or not parsed.path.endswith('/viewform'):
        raise ValueError('Некорректная ссылка формы')
    if not field.startswith('entry.') or not field[6:].isdigit():
        raise ValueError('Некорректное поле диагностики')
    return url + '?' + urlencode({'usp': 'pp_url', field: report})


class ReportWindow(tk.Toplevel):
    def __init__(self, parent, app, palette):
        super().__init__(parent)
        self.title('Сообщить об ошибке')
        self.transient(parent)
        self.geometry('840x740')
        self.minsize(680, 540)
        self.configure(bg=palette['card'])
        style = ttk.Style(self)
        style.configure('Report.Background.TFrame',background=palette['card'])
        style.configure('Report.Background.TLabel',background=palette['card'],foreground=palette['text'])
        style.configure('Report.BackgroundHint.TLabel',background=palette['card'],foreground=palette['muted'],font=('Bahnschrift',11))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = ttk.Frame(self,style='Report.Background.TFrame',padding=(22,18))
        header.grid(row=0,column=0,sticky='ew')
        ttk.Label(header,text='Помогу разобраться',style='Report.Background.TLabel',font=('Bahnschrift',25,'bold')).pack(anchor='w')
        ttk.Label(header,text='Проверьте отчёт, затем откройте форму.',style='Report.Background.TLabel',font=('Bahnschrift',15,'bold')).pack(anchor='w',pady=(8,4))
        ttk.Label(header,text='В форме можно описать проблему и добавить скриншоты. Нужен вход в Google. '
                  'При загрузке файлов Google сохраняет имя и адрес почты. Контакт для ответа необязателен.',
                  style='Report.BackgroundHint.TLabel',wraplength=770).pack(anchor='w')
        soft = '#e7f6fc' if palette['bg'] != '#141d30' and palette['card'] == '#ffffff' else palette['soft']
        self.report_images = []
        def rounded_style(name,color,button=False):
            bitmap=Image.new('RGB',(40,40),palette['card'])
            ImageDraw.Draw(bitmap).rounded_rectangle((0,0,39,39),radius=12,fill=color,outline=palette['line'])
            photo=ImageTk.PhotoImage(bitmap,master=self)
            self.report_images.append(photo)
            element=name+str(id(self))
            style.element_create(element,'image',photo,border=13,sticky='nsew')
            children=[('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})] if button else []
            options={'sticky':'nsew'}
            if children:
                options['children']=children
            style.layout(name,[(element,options)])
        rounded_style('Report.Card.TFrame',soft)
        rounded_style('Report.Pink.TButton',palette['pink'],True)
        rounded_style('Report.Copy.TButton',palette['card'],True)
        style.configure('Report.Pink.TButton',font=('Bahnschrift',12,'bold'),padding=(16,9),foreground=palette['text'])
        style.configure('Report.Copy.TButton',font=('Bahnschrift',12,'bold'),padding=(14,9),foreground=palette['text'])
        style.configure('Report.Title.TLabel',background=soft,foreground=palette['text'],font=('Bahnschrift',16,'bold'))
        style.configure('Report.Hint.TLabel',background=soft,foreground=palette['muted'],font=('Bahnschrift',10))
        style.configure('Report.Inner.TFrame',background=soft)
        frame = ttk.Frame(self, style='Report.Card.TFrame',padding=(12,12))
        frame.grid(row=1, column=0, sticky='nsew',padx=22)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        report_header=ttk.Frame(frame,style='Report.Inner.TFrame')
        report_header.grid(row=0,column=0,columnspan=2,sticky='ew',padx=8,pady=(0,10))
        ttk.Label(report_header,text='Технический отчёт',style='Report.Title.TLabel').pack(side='left')
        ttk.Label(report_header,text='Можно выделить и скопировать текст',style='Report.Hint.TLabel').pack(side='right')
        self.text = tk.Text(frame, wrap='word', font=('Consolas', 11), bg=palette['card'],
                            fg=palette['text'], borderwidth=0, padx=12, pady=12)
        self.text.grid(row=1, column=0, sticky='nsew')
        self.report = build_report(app)
        self.text.insert('1.0', self.report)
        self.text.configure(state='disabled')
        bar = PinkScrollbar(frame, self.text.yview,soft)
        bar.grid(row=1, column=1, sticky='ns',padx=(5,0))
        self.text.configure(yscrollcommand=bar.set)
        privacy = ttk.Frame(self,style='Report.Card.TFrame',padding=(12,8))
        privacy.grid(row=2,column=0,sticky='ew',padx=22,pady=(10,0))
        shield=tk.Canvas(privacy,width=28,height=30,bg=soft,highlightthickness=0)
        shield.pack(side='left',padx=(4,10))
        shield.create_polygon(14,2,25,7,24,19,20,25,14,29,8,25,4,19,3,7,
                              fill='',outline=palette['text'],width=2)
        ttk.Label(privacy,text='В отчёт не входят личные данные, адреса подключения и игровые балансы.',
                  style='Report.Hint.TLabel',wraplength=700).pack(side='left')
        self.progress = tk.StringVar(value='Проверяем размеры выбранных окон…')
        ttk.Label(self,textvariable=self.progress,style='Report.BackgroundHint.TLabel').grid(row=3,column=0,sticky='w',padx=22,pady=(6,0))
        footer = ttk.Frame(self,style='Report.Background.TFrame',padding=(22,12))
        footer.grid(row=4, column=0, sticky='ew')
        self.copy_button=ttk.Button(footer,text='▣  Скопировать отчёт',style='Report.Copy.TButton',command=self.copy_report)
        self.copy_button.pack(side='left')
        self.open_button=ttk.Button(footer,text='Открыть форму с отчётом',style='Report.Pink.TButton',command=self.open_form)
        self.open_button.pack(side='right')
        self.copy_button.configure(state='disabled')
        self.open_button.configure(state='disabled')
        self._copy_job = None
        self._size_job = None
        self._size_results = queue.Queue()
        monitors = report_monitors(app)
        def worker():
            self._size_results.put(read_display_sizes(monitors))
        threading.Thread(target=worker,name='kgpm-report-display-sizes',daemon=True).start()
        self._app = app
        self._size_job = self.after(80,self.collect_sizes)

    def collect_sizes(self):
        self._size_job = None
        try:
            sizes = self._size_results.get_nowait()
        except queue.Empty:
            self._size_job = self.after(80,self.collect_sizes)
            return
        self.report = build_report(self._app,sizes)
        self.text.configure(state='normal')
        self.text.delete('1.0','end')
        self.text.insert('1.0',self.report)
        self.text.configure(state='disabled')
        self.progress.set('Отчёт готов. Проверьте его перед отправкой.')
        self.copy_button.configure(state='normal')
        self.open_button.configure(state='normal')

    def destroy(self):
        for job in (getattr(self,'_copy_job',None),getattr(self,'_size_job',None)):
            if job:
                self.after_cancel(job)
        super().destroy()

    def copy_report(self):
        self.clipboard_clear()
        self.clipboard_append(self.report)
        if self._copy_job:
            self.after_cancel(self._copy_job)
        self.copy_button.configure(text='✓  Скопировано')
        def restore():
            self._copy_job=None
            self.copy_button.configure(text='▣  Скопировать отчёт')
        self._copy_job=self.after(2000,restore)

    def open_form(self):
        try:
            url = form_url(self.report)
        except (OSError, ValueError, KeyError):
            messagebox.showinfo('Форма ещё не подключена',
                'Ссылка формы пока не подключена. Можно скопировать отчёт и написать @casorin.', parent=self)
            return
        if not webbrowser.open(url):
            messagebox.showerror('Не удалось открыть браузер',
                'Скопируйте отчёт и напишите @casorin.', parent=self)
