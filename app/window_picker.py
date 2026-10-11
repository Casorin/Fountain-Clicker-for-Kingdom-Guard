import queue
import threading
import tkinter as tk
import uuid
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk
from app.memu_windows import discover_windows, preview_window
from app.connection_diagnostics import preview_error_message


def supported_preview(image):
    return (480 <= image.height <= 4096 and .5 <= image.width/image.height <= 2.5)


def picker_style_images(root, outer_color, preview_background):
    # Ttk elements live until the Tk interpreter closes, not until a picker closes.
    outer_color = tuple(value//256 for value in root.winfo_rgb(outer_color))
    cache = getattr(root, '_fountain_picker_styles', None)
    if cache is None:
        cache = root._fountain_picker_styles = {}
    key = (outer_color, preview_background)
    if key not in cache:
        style = ttk.Style(root)
        token = uuid.uuid4().hex
        images = []
        for role, size, radius, fill, border in (
                ('Panel',40,12,preview_background,13), ('Button',32,8,'#ffacd0',9)):
            image = Image.new('RGB',(size,size),outer_color)
            ImageDraw.Draw(image).rounded_rectangle((0,0,size-1,size-1),radius=radius,
                                                    fill=fill,outline='#cce8fb' if role == 'Panel' else fill)
            photo = ImageTk.PhotoImage(image,master=root)
            element = f'Picker{role}{token}'
            style.element_create(element,'image',photo,border=border,sticky='nsew')
            images.append((element,photo))
        cache[key] = images
    return cache[key]


class PinkScrollbar(tk.Canvas):
    """Slim rounded scrollbar with a draggable thumb and no arrow buttons."""
    def __init__(self, parent, command, background):
        super().__init__(parent, width=16, highlightthickness=0, bg=background)
        self.command = command
        self.first, self.last = 0.0, 1.0
        self.bind('<Configure>', lambda _event: self.draw())
        self.bind('<Button-1>', self.move)
        self.bind('<B1-Motion>', self.move)

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.draw()

    def draw(self):
        self.delete('all')
        height = max(16, self.winfo_height())
        self.create_line(8, 8, 8, height-8, width=10, fill='#fbe5ef', capstyle='round')
        if self.last-self.first < .999:
            top = 8+self.first*(height-16)
            bottom = max(top+18, 8+self.last*(height-16))
            self.create_line(8, top, 8, min(height-8, bottom), width=10,
                             fill='#eba0c2', capstyle='round')

    def move(self, event):
        span = self.last-self.first
        fraction = (event.y-8)/max(1, self.winfo_height()-16)-span/2
        self.command('moveto', max(0, min(1-span, fraction)))


class WindowPicker(tk.Toplevel):
    def __init__(self, root, adb_path, selected_serial, on_select, diagnostics=None):
        super().__init__(root)
        self.title('Выбор окон — Фонтан')
        width, height = min(1040, root.winfo_screenwidth()-80), min(740, root.winfo_screenheight()-100)
        self.geometry(f'{width}x{height}')
        self.minsize(min(720, width), min(560, height))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.transient(root)
        self.adb_path, self.on_select = adb_path, on_select
        self.selected_serials = {selected_serial} if isinstance(selected_serial, str) else set(selected_serial)
        self.checked = set()
        self.results = queue.Queue()
        self._cancelled = threading.Event()
        self.windows, self.images = {}, {}
        self.preview_errors = {}
        self.diagnostics = diagnostics if diagnostics is not None else []
        self.busy = False
        self.status = tk.StringVar(value='Ищем открытые эмуляторы…')
        ttk.Label(self, text='Выберите окно эмулятора', font=('Bahnschrift', 22, 'bold')).grid(row=0, column=0, sticky='w', padx=24, pady=(18,6))
        self.description = ttk.Label(self, text='Отметьте окна с общим призовым фондом.\nДля другого фонда откройте отдельное окно программы.', wraplength=700)
        self.description.grid(row=1, column=0, sticky='ew', padx=20)
        style = ttk.Style(self)
        self.configure(bg=style.lookup('TFrame','background') or '#edf7fc')
        background = style.lookup('Card.TFrame', 'background') or '#ffffff'
        background = '#%02x%02x%02x' % tuple(value//256 for value in self.winfo_rgb(background))
        foreground = style.lookup('TLabel', 'foreground') or '#0b174f'
        self.preview_foreground = foreground
        preview_background = '#eff9ff' if sum(self.winfo_rgb(background)) > 90000 else '#23334b'
        style.configure('Picker.Hint.TLabel',background=preview_background,
                        foreground=style.lookup('Muted.TLabel','foreground') or '#637cad',font=('Bahnschrift',10))
        style.configure('Picker.Title.TLabel',background=preview_background,foreground=foreground,font=('Bahnschrift',15,'bold'))
        (element,self.panel_image),(button_element,self.choose_image) = picker_style_images(
            root,self.cget('bg'),preview_background)
        style.layout('Picker.Preview.TFrame',[(element,{'sticky':'nsew'})])
        style.configure('Picker.Inner.TFrame',background=preview_background)
        style.layout('Picker.Primary.TButton',[(button_element,{'sticky':'nsew','children':[
            ('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})]})])
        style.configure('Picker.Primary.TButton',font=('Bahnschrift',12,'bold'),padding=(18,6),foreground=foreground)
        style.layout('Picker.Loading.TButton', style.layout('Picker.Primary.TButton'))
        style.configure('Picker.Loading.TButton', font=('Trebuchet MS',10,'bold'),
                        padding=(12,0), foreground='#141b45')
        style.map('Picker.Loading.TButton', foreground=[('disabled','#141b45')])
        style.configure('Picker.Horizontal.TProgressbar', background='#e875a9',
                        troughcolor=preview_background, borderwidth=0)
        style.configure('Picker.Treeview', background=background, fieldbackground=background,
                        foreground=foreground, rowheight=48, borderwidth=0,
                        font=('Bahnschrift', 12, 'bold'))
        style.map('Picker.Treeview', background=[('selected', preview_background)],
                  foreground=[('selected', foreground)])
        self.panes = tk.PanedWindow(self, orient='horizontal', sashwidth=8, sashpad=3,
                                   sashrelief='flat', bg='#f5d5e4', borderwidth=0)
        self.panes.grid(row=2, column=0, sticky='nsew', padx=24, pady=16)
        left = ttk.Frame(self.panes, style='RoundedCard.TFrame', padding=(14,12))
        right = ttk.Frame(self.panes, style='Picker.Preview.TFrame', padding=(14,12))
        self.panes.add(left, width=350, minsize=240, stretch='never')
        self.panes.add(right, minsize=260, stretch='always')
        self.sash_handle = tk.Label(self.panes,text='⋮',font=('Bahnschrift',16,'bold'),
                                   bg='#f5d5e4',fg='#b1658c',cursor='sb_h_double_arrow')
        self.sash_handle.bind('<Button-1>',lambda event: setattr(self,'_sash_offset',event.x))
        self.sash_handle.bind('<B1-Motion>',self.drag_panel)
        left.bind('<Configure>',lambda _event:self.position_handle())
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        ttk.Label(left, text='Открытые окна', style='Section.TLabel').grid(row=0,column=0,sticky='w')
        ttk.Label(left, text='Нажмите название, чтобы увидеть снимок', style='MutedCard.TLabel',
                  wraplength=280).grid(row=1,column=0,sticky='w',pady=(6,12))
        self.list = ttk.Treeview(left, columns=('checked', 'name'), displaycolumns=('name',),
                                 show='tree', height=3, selectmode='browse', style='Picker.Treeview')
        self.list.column('#0', width=46, minwidth=46, stretch=False)
        self.list.column('name', width=260, minwidth=80, stretch=True)
        self.list.grid(row=2,column=0,sticky='nsew')
        self.scrollbar = PinkScrollbar(left, self.list.yview, background)
        self.scrollbar.grid(row=2,column=1,sticky='ns',padx=(5,0))
        self.list.configure(yscrollcommand=self.scrollbar.set)
        self.checkbox_images = {}
        for checked in (False, True):
            image = Image.new('RGBA', (32,32))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((3,3,28,28), radius=6,
                                   fill='#ff659e' if checked else background,
                                   outline='#ff659e' if checked else '#8e9dbd', width=1)
            if checked:
                draw.line((9,15,14,20,23,10), fill='white', width=3)
            self.checkbox_images[checked] = ImageTk.PhotoImage(image, master=self)
        self.count = tk.StringVar(value='Выбрано: 0')
        ttk.Label(left, textvariable=self.count, style='Card.TLabel').grid(row=3,column=0,sticky='w',pady=(12,8))
        ttk.Separator(left).grid(row=4,column=0,columnspan=2,sticky='ew')
        ttk.Label(left,text='Настройки будут общими для выбранных окон.',style='MutedCard.TLabel',
                  wraplength=290).grid(row=5,column=0,sticky='w',pady=(8,0))
        self.list.bind('<<TreeviewSelect>>', self.show_preview)
        self.list.bind('<ButtonRelease-1>', self.toggle_checked)
        self.list.bind('<space>', self.toggle_checked)
        right.columnconfigure(0,weight=1)
        right.rowconfigure(1,weight=1)
        self.preview_name = tk.StringVar(value='Снимок окна')
        preview_header = ttk.Frame(right,style='Picker.Inner.TFrame')
        preview_header.grid(row=0,column=0,sticky='ew',pady=(0,8))
        ttk.Label(preview_header,textvariable=self.preview_name,style='Picker.Title.TLabel').pack(side='left')
        ttk.Label(preview_header,text='Снимок окна',style='Picker.Hint.TLabel').pack(side='right')
        self.preview = tk.Canvas(right, width=1, height=1, highlightthickness=0, bg=preview_background)
        self.preview.grid(row=1,column=0,sticky='nsew')
        ttk.Label(right,text='Проверьте, что открыт нужный аккаунт.',style='Picker.Hint.TLabel',
                  wraplength=350).grid(row=2,column=0,pady=(8,0))
        self.preview.bind('<Configure>', self.render_preview)
        self.status_label = ttk.Label(self, textvariable=self.status, wraplength=700)
        self.status_label.grid(row=3, column=0, sticky='ew', padx=24, pady=(0,8))
        controls = ttk.Frame(self)
        controls.grid(row=4, column=0, sticky='ew', padx=24, pady=(0,16))
        controls.columnconfigure(0, weight=1)
        refresh_controls = ttk.Frame(controls)
        refresh_controls.grid(row=0, column=0, sticky='w')
        self.refresh_button = ttk.Button(refresh_controls, text='↻  Обновить снимки', command=self.refresh, width=21)
        self.refresh_button.pack(side='left')
        self.refresh_progress = ttk.Progressbar(refresh_controls, length=90, mode='indeterminate',
                                               style='Picker.Horizontal.TProgressbar')
        self.choose_button = ttk.Button(controls, text='Выбрать окна', style='Picker.Primary.TButton', command=self.choose, state='disabled')
        self.choose_button.grid(row=0, column=2, sticky='e')
        self.choose_button.bind('<Button-1>', self.explain_disabled_choice)
        ttk.Button(controls, text='Отмена', command=self.destroy).grid(row=0, column=1, padx=10)
        self.bind('<Configure>', self.resize_text)
        self.grab_set()
        self.refresh()
        self._collect_job = self.after(50, self.collect)

    def destroy(self):
        cancelled = getattr(self, '_cancelled', None)
        if cancelled is not None:
            cancelled.set()
        progress = getattr(self, 'refresh_progress', None)
        if progress is not None and progress.winfo_exists():
            progress.stop()
        job = getattr(self, '_collect_job', None)
        if job is not None:
            self.after_cancel(job)
            self._collect_job = None
        if self.grab_current() is self:
            self.grab_release()
        super().destroy()

    def position_handle(self):
        x, _y = self.panes.sash_coord(0)
        self.sash_handle.place(x=x-3,rely=.5,anchor='w',width=14,height=42)
        self.sash_handle.lift()

    def drag_panel(self,event):
        x = event.x_root-self.panes.winfo_rootx()-getattr(self,'_sash_offset',0)+3
        self.panes.sash_place(0,x,0)
        self.position_handle()

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self.diagnostics.clear()
        self.preview_errors.clear()
        self.images.clear()
        self.choose_button.configure(state='disabled')
        self.refresh_button.configure(state='disabled', text='Обновляем снимки…',
                                      style='Picker.Loading.TButton', cursor='watch')
        self.refresh_progress.configure(mode='indeterminate', value=0)
        self.refresh_progress.pack(side='left', padx=(10,0))
        self.refresh_progress.start(30)
        self.status.set('Получаем снимки из эмуляторов. Нажатий в игре нет…')
        self.render_preview()
        def worker():
            try:
                warnings = []
                windows = discover_windows(self.adb_path, diagnostics=warnings)
                if self._cancelled.is_set():
                    return
                self.results.put(('list', windows))
                for provider, message in warnings:
                    self.results.put(('warning', provider, message))
                for window in windows:
                    if self._cancelled.is_set():
                        return
                    try:
                        self.results.put(('image', window.uuid, preview_window(self.adb_path, window)))
                    except Exception as exc:
                        self.results.put(('error', window.uuid, preview_error_message(exc)))
            except Exception as exc:
                self.results.put(('error', None, preview_error_message(exc)))
            finally:
                self.results.put(('done',))
        threading.Thread(target=worker, name='kgpm-window-previews', daemon=True).start()

    def collect(self):
        job = getattr(self, '_collect_job', None)
        if job is not None:
            self.after_cancel(job)
            self._collect_job = None
        if not self.winfo_exists():
            return
        while not self.results.empty():
            item = self.results.get()
            if item[0] == 'list':
                self.list.delete(*self.list.get_children())
                self.windows = {w.uuid: w for w in item[1]}
                self.refresh_progress.stop()
                self.refresh_progress.configure(mode='determinate', maximum=max(1,len(self.windows)), value=0)
                self.images.clear()
                self.checked.clear()
                for window in item[1]:
                    if window.serial in self.selected_serials:
                        self.checked.add(window.uuid)
                    self.list.insert('', 'end', iid=window.uuid, image=self.checkbox_images[window.uuid in self.checked],
                                     values=('☑' if window.uuid in self.checked else '☐', window.name))
                chosen = next((w.uuid for w in item[1] if w.serial in self.selected_serials), next(iter(self.windows), None))
                if chosen:
                    self.list.selection_set(chosen)
                else:
                    self.status.set('Нет доступных открытых эмуляторов. Проверьте локальное подключение ADB в их настройках.')
            elif item[0] == 'image':
                self.images[item[1]] = item[2]
                window = self.windows[item[1]]
                size = item[2].size
                self.diagnostics.append((window.provider, f'Снимок {size[0]} × {size[1]}; размер поддерживается: {supported_preview(item[2])}'))
                self.show_preview()
            elif item[0] == 'error':
                self.preview_errors[item[1]] = item[-1]
                window = self.windows.get(item[1])
                self.diagnostics.append((window.provider if window else 'Поиск окон', item[-1]))
                self.status.set(item[-1])
                self.render_preview()
            elif item[0] == 'warning':
                self.diagnostics.append((item[1], item[2]))
                self.status.set(item[1] + ': ' + item[2])
                if not self.windows:
                    self.preview_errors[None] = item[2]
                    self.render_preview()
            elif item[0] == 'done':
                self.busy = False
                self.refresh_progress.stop()
                self.refresh_progress.pack_forget()
                self.refresh_button.configure(state='normal', text='↻  Обновить снимки', style='TButton', cursor='')
                self.show_preview()
            if item[0] in {'image','error'} and item[1] in self.windows:
                completed = len(set(self.images) | (set(self.preview_errors) & set(self.windows)))
                self.refresh_progress.configure(value=completed)
        self._collect_job = self.after(50, self.collect)

    def show_preview(self, _event=None):
        selected = self.list.selection()
        if selected and selected[0] in self.windows:
            self.preview_name.set(self.windows[selected[0]].name)
        if not selected or selected[0] not in self.images:
            if selected and selected[0] in self.preview_errors:
                self.status.set(self.preview_errors[selected[0]])
            self.render_preview()
            self.update_choice()
            return
        image = self.images[selected[0]]
        supported = supported_preview(image)
        self.status.set(f'Снимок выбранного окна · {image.width} × {image.height}. '
                        + ('Поставьте галочки у нужных окон. Настройки будут общими.' if supported else
                           'Этот размер экрана пока не поддерживается. Выбор запрещён.'))
        self.render_preview()
        self.update_choice()

    def resize_text(self, event):
        if event.widget is self:
            self.description.configure(wraplength=max(300, event.width-40))
            self.status_label.configure(wraplength=max(300, event.width-40))

    def render_preview(self, _event=None):
        self.preview.delete('all')
        selected = self.list.selection()
        width, height = self.preview.winfo_width(), self.preview.winfo_height()
        if not selected or selected[0] not in self.images:
            error = self.preview_errors.get(selected[0] if selected else None) or self.preview_errors.get(None)
            if error:
                self.preview.create_text(width//2, max(30, height//2-65),
                                         text='Не удалось получить снимок',
                                         fill=self.preview_foreground, font=('Bahnschrift', 16, 'bold'),
                                         width=max(100, width-48), justify='center')
                self.preview.create_text(width//2, height//2,
                                         text=error, fill=self.preview_foreground,
                                         font=('Bahnschrift', 12), width=max(100, width-48),
                                         justify='center', anchor='n')
            else:
                self.preview.create_text(width//2, height//2,
                                         text='Получаем снимок…' if self.busy else 'Предпросмотр пока недоступен',
                                         fill=self.preview_foreground)
            return
        thumbnail = self.images[selected[0]].copy()
        thumbnail.thumbnail((max(1, width-10), max(1, height-10)))
        self.photo = ImageTk.PhotoImage(thumbnail, master=self)
        self.preview.create_image(width//2, height//2, image=self.photo)

    def toggle_checked(self, event):
        if event.keysym == 'space':
            selected = self.list.selection()
            item = selected[0] if selected else ''
        else:
            if self.list.identify_column(event.x) != '#0':
                return
            item = self.list.identify_row(event.y)
        if item not in self.images or not supported_preview(self.images[item]):
            self.status.set(self.preview_errors.get(item, 'Сначала дождитесь снимка с поддерживаемым размером экрана.'))
            return
        if item in self.checked:
            self.checked.remove(item)
        else:
            self.checked.add(item)
        self.list.set(item, 'checked', '☑' if item in self.checked else '☐')
        self.list.item(item, image=self.checkbox_images[item in self.checked])
        self.update_choice()

    def update_choice(self):
        valid = bool(self.checked) and all(i in self.images and supported_preview(self.images[i]) for i in self.checked)
        count = len(self.checked)
        self.count.set(f'Выбрано: {count}')
        ending = 'окно' if count % 10 == 1 and count % 100 != 11 else 'окна' if count % 10 in (2,3,4) and count % 100 not in (12,13,14) else 'окон'
        self.choose_button.configure(state='normal' if valid else 'disabled', text=f'Выбрать {count} {ending}')

    def choose(self):
        if self.checked and all(i in self.images and supported_preview(self.images[i]) for i in self.checked):
            windows = [w for w in self.windows.values() if w.uuid in self.checked]
            self.destroy()
            self.on_select(windows)

    def explain_disabled_choice(self, _event=None):
        if not self.choose_button.instate(['disabled']):
            return
        if self.busy:
            self.status.set('Ещё получаем снимки. Дождитесь завершения загрузки, затем поставьте галочки у нужных окон.')
        elif not self.checked:
            self.status.set('Поставьте галочку слева от названия нужного окна. Если галочка не ставится, нажмите на название и прочитайте подсказку справа.')
        else:
            self.status.set('Не у всех отмеченных окон есть подходящий снимок. Обновите снимки или снимите галочки с недоступных окон.')
        return 'break'
