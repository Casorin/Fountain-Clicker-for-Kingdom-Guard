"""Presentation only: no OCR, reset, scheduling, or input decisions."""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk


PALETTES = {
    "light": dict(bg="#edf6fc", card="#ffffff", hero="#d7f1ff", text="#101a4b",
                  muted="#55729b", line="#c8e2f5", pink="#ff98bb", hover="#ffb2cd",
                  green="#a6f0d6", row="#eaf7ff", entry="#ffffff", soft="#f1f8fe"),
    "dark": dict(bg="#141b30", card="#202b43", hero="#253d58", text="#edf4ff",
                 muted="#b0c4df", line="#405775", pink="#ed8eaf", hover="#f7acc6",
                 green="#277861", row="#2a3b54", entry="#182339", soft="#253248"),
}


def rounded(canvas, x1, y1, x2, y2, radius, **options):
    return canvas.create_polygon(x1+radius,y1, x2-radius,y1, x2,y1, x2,y1+radius,
        x2,y2-radius, x2,y2, x2-radius,y2, x1+radius,y2, x1,y2, x1,y2-radius,
        x1,y1+radius, x1,y1, smooth=True, splinesteps=24, **options)


class ModeSwitch(tk.Canvas):
    def __init__(self, parent, command):
        super().__init__(parent, width=300, height=48, highlightthickness=0, takefocus=True, cursor="hand2")
        self.command = command
        self.selected = False
        self.palette = PALETTES['light']
        self.bind('<Button-1>', lambda event: command(event.x >= self.winfo_width()/2))
        self.bind('<Left>', lambda _: command(False))
        self.bind('<Right>', lambda _: command(True))
        self.bind('<Configure>', lambda _: self.draw())

    def draw(self):
        p = self.palette
        self.configure(bg=p['hero'])
        self.delete('all')
        w, h = max(300,self.winfo_width()), 48
        rounded(self, 1,1,w-1,h-1,14,fill=p['card'],outline=p['pink'],width=2)
        x = w/2 if self.selected else 3
        rounded(self,x,3,x+w/2-4,h-3,12,fill=p['pink'],outline='')
        for index,(xpos, label) in enumerate(((w/4,'Без кликов'),(3*w/4,'С кликами'))):
            self.create_text(xpos,h/2,text=label,fill='#101a4b' if bool(index)==self.selected else p['text'],font=('Bahnschrift',15))


class StartRuleSwitch(tk.Canvas):
    def __init__(self, parent, variable):
        super().__init__(parent, width=300, height=38, highlightthickness=0,
                         takefocus=True, cursor='hand2')
        self.variable = variable
        self.palette = PALETTES['light']
        self.bind('<Button-1>', lambda event: variable.set('percent' if event.x >= self.winfo_width()*.41 else 'range'))
        self.bind('<Left>', lambda _: variable.set('range'))
        self.bind('<Right>', lambda _: variable.set('percent'))
        self.bind('<Configure>', lambda _: self.draw())
        variable.trace_add('write', lambda *_: self.draw())

    def draw(self):
        p = self.palette
        self.configure(bg=p['card'])
        self.delete('all')
        w = max(300, self.winfo_width())
        rounded(self, 1, 1, w-1, 37, 9, fill=p['card'], outline=p['line'])
        selected = self.variable.get() == 'percent'
        x, end = (w*.41, w-3) if selected else (3, w*.41)
        rounded(self, x, 2, end, 36, 8, fill=p['pink'], outline='')
        for index, label in enumerate(('По сумме', 'По прошлому фонду')):
            self.create_text(w*(.205 if index == 0 else .705), 19, text=label, fill=p['text'],
                             font=('Trebuchet MS', 10, 'bold' if bool(index) == selected else 'normal'))


class ThresholdCard(tk.Canvas):
    def __init__(self, parent, variable):
        super().__init__(parent, height=40, highlightthickness=0)
        self.variable, self.palette = variable, PALETTES['light']
        self.bind('<Configure>', lambda _: self.draw())
        variable.trace_add('write', lambda *_: self.draw())

    def draw(self):
        p = self.palette
        self.configure(bg=p['card'])
        self.delete('all')
        w = max(650, self.winfo_width())
        rounded(self, 0, 0, w, 40, 12, fill=p['soft'], outline='')
        label = self.variable.get()
        percent = '%' in label
        number = label.split('от ', 1)[1] if percent and 'от ' in label else label
        if 'ждём' in label:
            number = 'Ждём обнуление'
        self.create_text(12, 20, text='Начнём при фонде', anchor='w', fill=p['muted'], font=('Trebuchet MS', 10))
        self.create_text(155, 20, text=number, anchor='w', fill=p['text'], font=('Bahnschrift', 17, 'bold'))
        if percent and 'от ' in label:
            self.create_line(305, 8, 305, 32, fill=p['line'])
            self.create_text(325, 20, text=label.split('%',1)[0]+'% от прошлого фонда', anchor='w',
                             fill=p['muted'], font=('Trebuchet MS', 10))
        if percent and w >= 1000:
            self.create_text(w-18, 29, text='Считаем от последнего подтверждённого фонда.', anchor='e',
                             fill=p['muted'], font=('Trebuchet MS', 10))


class ActionButton(tk.Canvas):
    def __init__(self, parent, text, command, primary=False, text_font=None):
        super().__init__(parent, height=48, width=1, highlightthickness=0, takefocus=True, cursor='hand2')
        self.text, self.command, self.primary = text, command, primary
        self.text_font = text_font or ('Trebuchet MS', 14, 'bold')
        self.palette = PALETTES['light']
        self.bind('<Button-1>', lambda _: self.invoke())
        self.bind('<Return>', lambda _: self.invoke())
        self.bind('<space>', lambda _: self.invoke())
        self.bind('<Configure>', lambda _: self.draw())
        self.bind('<FocusIn>', lambda _: self.draw())
        self.bind('<FocusOut>', lambda _: self.draw())

    def invoke(self):
        self.command()

    def cget(self, key):
        return self.text if key == 'text' else super().cget(key)

    def configure(self, cnf=None, **kwargs):
        if 'text' in kwargs:
            self.text = kwargs.pop('text')
        result = super().configure(cnf, **kwargs)
        if hasattr(self, 'palette'):
            self.draw()
        return result

    def draw(self):
        p = self.palette
        super().configure(bg=p['card'])
        self.delete('all')
        w = max(100, self.winfo_width())
        rounded(self, 1, 1, w-1, 47, 13, fill=p['pink'] if self.primary else p['card'],
                outline=p['pink'] if self.primary else p['line'], width=1)
        if self.primary:
            gradient = Image.new('RGB', (w, 48), p['card'])
            pen = ImageDraw.Draw(gradient)
            top = tuple(int(p['hover'][i:i+2],16) for i in (1,3,5))
            bottom = tuple(int(p['pink'][i:i+2],16) for i in (1,3,5))
            for y in range(48):
                color = tuple(round(a+(b-a)*y/47) for a,b in zip(top,bottom))
                pen.line((0,y,w,y),fill=color)
            mask = Image.new('L', (w,48),0)
            ImageDraw.Draw(mask).rounded_rectangle((1,1,w-2,46),radius=12,fill=255)
            background = Image.new('RGB',(w,48),p['card'])
            background.paste(gradient,(0,0),mask)
            self.gradient_image = ImageTk.PhotoImage(background,master=self)
            self.create_image(0,0,image=self.gradient_image,anchor='nw')
            self.create_text(w/2-26, 24, text=self.text.split(' / ')[0],
                             fill='#101a4b', font=('Segoe UI Black', 17))
            rounded(self, w/2+75, 10, w/2+113, 38, 9, fill='#ffc8dc', outline='')
            self.create_text(w/2+94, 24, text='F8', fill='#101a4b', font=('Bahnschrift', 12, 'bold'))
        else:
            self.create_text(w/2, 24, text=self.text, fill=p['text'], font=self.text_font)
        # A ttk combobox popdown is a Tcl-only window, not a Python widget.
        if str(self.tk.call('focus')) == str(self):
            rounded(self, 4, 4, w-4, 44, 11, fill='', outline=p['muted'])


class VisibilityBadge(tk.Canvas):
    def __init__(self, parent, variable):
        super().__init__(parent,width=185,height=40,highlightthickness=0)
        self.variable=variable
        self.palette=PALETTES['light']
        variable.trace_add('write', lambda *_: self.draw())

    def draw(self):
        p=self.palette
        self.configure(bg=p['hero'])
        self.delete('all')
        color=p['green'] if self.variable.get()=='Число видно' else ('#fff0c7' if p is PALETTES['light'] else '#665332')
        rounded(self,0,0,184,39,18,fill=color,outline='')
        self.create_text(92,20,text=self.variable.get(),fill=p['text'],font=('Bahnschrift',11))


def load_theme(path: Path) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("theme")
        return value if value in PALETTES else "light"
    except (OSError, ValueError, TypeError):
        return "light"


class FountainDesign:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.preferences = app.config.runtime_dir / "ui_preferences.json"
        self.theme = load_theme(self.preferences)
        self.details_open = False
        self.dragging = None
        from app.version import APP_VERSION
        self.root.title(f"Фонтан {APP_VERSION} — Kingdom Guard")
        self.root.geometry("840x890")
        self.root.minsize(840, 760)
        app._closed_window_width = 840
        self.status = tk.StringVar()
        self.visibility = tk.StringVar()
        self.theme_label = tk.StringVar()
        self.health = tk.StringVar(value="Проверяем подключение к игре")
        if not hasattr(app, 'start_method_var'):
            app.start_method_var = tk.StringVar(value='range')
            app.start_percent_var = tk.StringVar(value='85')
        self.settings_note = tk.StringVar()
        if not hasattr(app, 'click_speed_var'):
            app.click_speed_var = tk.StringVar(value='5')
        if not hasattr(app, 'percent_floor_enabled_var'):
            app.percent_floor_enabled_var = tk.BooleanVar(value=False)
            app.percent_floor_var = tk.StringVar(value='90000')
        self.saved_settings = self.settings_values()
        app.paned = ttk.PanedWindow(self.root, orient="horizontal")
        app.paned.pack(fill="both", expand=True, padx=12, pady=10)
        frame = ttk.Frame(app.paned)
        app.main_frame = frame
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        self.card_row = 2
        app.paned.add(frame, weight=1)
        from app.ui import LogPanel
        app.log_panel = LogPanel(app.paned,on_close=app.toggle_logs)
        app.log = app.log_panel.text
        top = ttk.Frame(frame)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(top, text="Фонтан", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="  /  Kingdom Guard", style="Muted.TLabel").pack(side="left", padx=8)
        ttk.Button(top, textvariable=self.theme_label, style="Icon.TButton", command=self.toggle_theme, width=3).pack(side="right")
        ttk.Button(top, text="Выбрать окно\nэмулятора", style='Top.TButton', command=app.choose_window).pack(side="right", padx=(12, 10))
        if hasattr(app, 'open_program_window'):
            app.other_program_button = ttk.Button(top, text="Доп. окно\nпрограммы", style='Top.TButton',command=app.open_program_window)
            app.other_program_button.pack(side="right", padx=4)
        self.help_button = ttk.Button(top, text="ⓘ", style="Help.Icon.TButton", command=self.open_help, width=3)
        self.help_button.pack(side="right", padx=4)

        hero = ttk.Frame(frame, style="RoundedHero.TFrame", padding=(16, 6))
        hero.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        hero.columnconfigure(0, weight=1)
        app.group_frame = ttk.Frame(hero, style='Hero.TFrame')
        ttk.Label(app.group_frame, text='Выбранные окна', style='HeroHint.TLabel').pack(side='left', padx=(0,10))
        picker_border=ttk.Frame(app.group_frame,style='Input.TFrame',padding=(5,2))
        picker_border.pack(side='left',fill='x',expand=True)
        app.group_picker = ttk.Combobox(picker_border, state='readonly', width=38, style='Window.TCombobox')
        app.group_picker.pack(fill='x',expand=True)
        app._group_picker_ids = []
        app.group_picker.bind('<<ComboboxSelected>>', app._focus_session)
        left = ttk.Frame(hero, style="Hero.TFrame")
        left.grid(row=0, column=0, sticky='ew')
        ttk.Label(left, text="Призовой фонд", style="HeroTitle.TLabel").pack(anchor="w")
        fund = ttk.Frame(left, style="Hero.TFrame")
        fund.pack(anchor="w")
        ttk.Label(fund, textvariable=app.value_var, style="BigFund.TLabel").pack(side="left")
        self.badge = VisibilityBadge(fund,self.visibility)
        self.badge.pack(side="left", padx=18)
        modes = ttk.Frame(hero, style="Hero.TFrame")
        modes.grid(row=0, column=1, padx=(10,0))
        self.mode_switch=ModeSwitch(modes,self.choose_mode)
        self.mode_switch.pack()
        self.daily_reward_warning = ttk.Label(
            modes, text='Рекомендуемое разрешение: 1080 × 1080.',
            style='HeroWarning.TLabel', justify='center', wraplength=300)
        app.mode_var.trace_add('write', lambda *_: self.update_daily_reward_warning())
        self.update_daily_reward_warning()

        self.action_guidance = tk.StringVar()
        self.guidance_label = ttk.Label(hero, textvariable=self.action_guidance,
                                        style='HeroHint.TLabel', wraplength=740, justify='left')
        self.guidance_label.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(4, 0))
        self.guidance_label.grid_remove()

        self.history_splitter = ttk.PanedWindow(frame, orient='vertical')
        self.history_splitter.grid(row=2, column=0, sticky='nsew', pady=(0,8))
        card = self.card(self.history_splitter)
        ttk.Label(card, text="Когда начинать клики", style="SettingsSection.TLabel").pack(anchor="w")
        start_rule = ttk.Frame(card, style='Card.TFrame')
        start_rule.pack(fill='x', pady=(4, 2))
        self.start_rule_switch = StartRuleSwitch(start_rule, app.start_method_var)
        self.start_rule_switch.pack(side='left')
        self.percent_box = ttk.Frame(card, style='Card.TFrame')
        percent_controls = ttk.Frame(self.percent_box, style='Card.TFrame')
        percent_controls.pack(side='left')
        ttk.Label(percent_controls, text='Доля прошлого фонда', style='MutedCard.TLabel').pack(anchor='w')
        percent_input = ttk.Frame(percent_controls, style='Input.TFrame', padding=(10, 1))
        percent_input.pack(anchor='w', pady=(4, 0))
        self.percent_entry = ttk.Entry(percent_input, textvariable=app.start_percent_var,
                    width=5, font=('Bahnschrift', 13, 'bold'))
        self.percent_entry.pack(side='left')
        ttk.Label(percent_input, text='%', style='Percent.TLabel').pack(side='left', padx=(6, 2))
        self.percent_threshold = tk.StringVar(value='Ждём новое обнуление')
        threshold_box = ttk.Frame(self.percent_box, style='Card.TFrame')
        self.percent_threshold_box = threshold_box
        threshold_box.pack(side='left', padx=(24,0))
        ttk.Label(threshold_box, text='Начнём при фонде', style='MutedCard.TLabel').pack(anchor='w')
        ttk.Label(threshold_box, textvariable=self.percent_threshold, style='WalletValue.TLabel').pack(anchor='w',pady=(4,0))
        app.start_percent_var.trace_add('write',lambda *_:self.update_percent_preview())
        floor_controls = ttk.Frame(self.percent_box, style='Card.TFrame')
        floor_controls.pack(side='left', padx=(24,0), before=threshold_box)
        self.percent_floor_check = ttk.Checkbutton(
            floor_controls, text='Но не меньше', variable=app.percent_floor_enabled_var,
            style='SmallWallet.Card.TCheckbutton', command=self.update_percent_preview)
        self.percent_floor_check.pack(anchor='w')
        self.percent_floor_entry = ttk.Entry(floor_controls, textvariable=app.percent_floor_var,
                                           width=11, font=('Bahnschrift',13,'bold'))
        self.percent_floor_entry.pack(anchor='w', pady=(4,0))
        for variable in (app.percent_floor_enabled_var, app.percent_floor_var):
            variable.trace_add('write', lambda *_: (self.update_percent_preview(), self.update_settings_hint()))
        entries = ttk.Frame(card, style="Card.TFrame")
        self.range_entries = entries
        entries.pack(fill="x", pady=(2, 2))
        entries.columnconfigure(0, weight=1)
        entries.columnconfigure(1, weight=1)
        for col, text, variable in ((0, "От", app.test_range_min_var), (1, "До", app.test_range_max_var)):
            box = ttk.Frame(entries, style="Card.TFrame")
            box.grid(row=0, column=col, sticky="ew", padx=(0, 16) if col == 0 else (0, 0))
            ttk.Label(box, text=text, style="Card.TLabel").pack(anchor="w", pady=(0, 1))
            border=ttk.Frame(box, style='Input.TFrame', padding=(10,1))
            border.pack(fill='x')
            field=ttk.Spinbox(border, textvariable=variable, from_=1000, to=999999, increment=500,
                        width=12, font=("Bahnschrift", 13, "bold"))
            field.pack(fill="x")
            if col==1:
                self.upper_entry=field
            variable.trace_add("write", lambda *_: self.draw_range())
        ttk.Checkbutton(entries,text="Без верхнего предела",variable=app.no_upper_var,
                        command=self.update_upper_entry,style='Card.TCheckbutton').grid(row=0,column=2,padx=(18,0),sticky='s',pady=8)
        self.slider = tk.Canvas(card, height=48, highlightthickness=0)
        self.slider.pack(fill="x", pady=(2, 0))
        self.slider.bind("<Configure>", lambda _: self.draw_range())
        self.slider.bind("<Button-1>", self.begin_drag)
        self.slider.bind("<B1-Motion>", self.drag_range)
        self.slider.bind("<ButtonRelease-1>", lambda _: setattr(self, "dragging", None))
        range_line = ttk.Frame(card, style="Card.TFrame")
        self.range_line = range_line
        range_line.pack(fill="x")
        self.threshold_card = ThresholdCard(range_line, app.active_range_var)
        self.threshold_card.pack(fill='x', pady=(2, 4))
        self.settings_separator = ttk.Separator(card)
        self.settings_separator.pack(fill='x', pady=(2, 4))
        wallet = ttk.Frame(card,style='Card.TFrame')
        wallet.pack(fill='x',pady=(1,1))
        ttk.Checkbutton(wallet,text="Оставить на счёте",variable=app.gem_limit_enabled_var,
                        style='Wallet.Card.TCheckbutton').pack(side='left')
        wallet_input=ttk.Frame(wallet,style='Input.TFrame',padding=(8,1))
        wallet_input.pack(side='left',padx=10)
        ttk.Spinbox(wallet_input,textvariable=app.gem_floor_var,from_=0,to=99999999,increment=1000,width=10,font=('Bahnschrift',13)).pack()
        ttk.Label(wallet,text='самоцветов',style='Card.TLabel').pack(side='left')
        balance_box=ttk.Frame(wallet,style='Card.TFrame')
        balance_box.pack(side='right')
        ttk.Label(balance_box,text='Сейчас на счёте',style='MutedCard.TLabel').pack(anchor='e')
        self.wallet_value = tk.StringVar()
        ttk.Label(balance_box,textvariable=self.wallet_value,style='WalletValue.TLabel').pack(anchor='e')
        save_row=ttk.Frame(card,style='Card.TFrame')
        save_row.pack(fill='x',pady=(2,2))
        speed_box = ttk.Frame(save_row, style='Card.TFrame')
        speed_box.pack(side='left', padx=(0, 12))
        ttk.Label(speed_box, text='Кликов в секунду', style='MutedCard.TLabel').pack(side='left', padx=(0, 6))
        self.click_speed_input = ttk.Spinbox(speed_box, textvariable=app.click_speed_var,
                                           from_=1, to=10, width=3, font=('Bahnschrift', 11))
        self.click_speed_input.pack(side='left')
        self.settings_hint=ttk.Label(save_row,textvariable=self.settings_note,style='MutedCard.TLabel',wraplength=270)
        self.settings_hint.pack(side='left', fill='x', expand=True)
        self.save_button=ttk.Button(save_row,text='Сохранить настройки',style='Save.TButton',command=app.apply_range)
        self.save_button.pack(side='right')
        ttk.Separator(card).pack(fill='x',pady=(2,4))
        for variable in (app.test_range_min_var,app.test_range_max_var,app.no_upper_var,
                         app.gem_limit_enabled_var,app.gem_floor_var,app.start_method_var,app.start_percent_var,app.click_speed_var):
            variable.trace_add('write',lambda *_: self.update_settings_hint())
        self.update_settings_hint()
        controls = ttk.Frame(card, style="Card.TFrame")
        controls.pack(fill="x", pady=(0, 3))
        controls.columnconfigure(0,weight=2,uniform='actions')
        controls.columnconfigure(1,weight=1,uniform='actions')
        self.start_button = ActionButton(controls, text="Начать / F8", command=app.toggle, primary=True)
        self.start_button.grid(row=0,column=0,sticky='ew',padx=(0,20))
        self.restart_button = ActionButton(controls,text='↻  Ждать новое обнуление',command=app.reset_lock,
                                           text_font=('Trebuchet MS',11,'bold'))
        self.restart_button.grid(row=0,column=1,sticky='ew')

        stats = self.card(self.history_splitter, expand=True)
        self.history_splitter.bind('<Map>', self.set_initial_history_size, add='+')
        header = ttk.Frame(stats, style="Card.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="История обнулений", style="Section.TLabel").pack(side="left")
        app.clear_history_button = ttk.Button(header, text="Очистить историю", command=app.clear_all_history)
        app.clear_history_button.pack(side="right")
        summary = ttk.Frame(stats, style="Soft.TFrame", padding=(20, 6))
        summary.pack(fill="x", pady=(4, 4))
        for text, var in (("После обнуления", app.reset_since_var), ("Средний интервал", app.reset_average_var)):
            column = ttk.Frame(summary, style="Soft.TFrame")
            column.pack(side="left", expand=True)
            ttk.Label(column, text=text, style="SoftHint.TLabel").pack(side='left', padx=(0, 10))
            ttk.Label(column, textvariable=var, style="SoftStat.TLabel").pack(side='left')
        table_frame = ttk.Frame(stats, style="Card.TFrame")
        table_frame.pack(fill="both", expand=True)
        table_frame.columnconfigure(0,weight=1)
        table_frame.rowconfigure(0,weight=1)
        app.history_table = ttk.Treeview(table_frame, columns=("index", "time", "peak", "interval"),
                                         displaycolumns=("time", "peak", "interval"), show="headings", height=5)
        for column, title, width in (("time", "Время", 240), ("peak", "Фонд перед обнулением", 290),
                                     ("interval", "Интервал", 210)):
            alignment = 'w' if column == 'time' else 'center'
            app.history_table.heading(column, text=title, anchor=alignment)
            app.history_table.column(column, width=width, minwidth=150 if column!='time' else 240, anchor=alignment, stretch=True)
        app.history_table.grid(row=0,column=0,sticky='nsew')
        from app.window_picker import PinkScrollbar
        self.history_scrollbar = PinkScrollbar(table_frame,app.history_table.yview,PALETTES[self.theme]['card'])
        self.history_scrollbar.grid(row=0,column=1,sticky='ns')
        app.history_table.configure(yscrollcommand=self.history_scrollbar.set)
        self.empty_history = tk.Canvas(app.history_table,highlightthickness=0,height=72)
        app.history_table.bind('<Configure>',lambda _event:self.update_empty_history(),add='+')
        self.latest_badge=tk.Canvas(app.history_table,width=100,height=26,highlightthickness=0)
        actions = ttk.Frame(stats, style="Card.TFrame")
        actions.pack(side="bottom", fill="x", before=table_frame, pady=(6, 0))
        actions.pack_forget()

        self.history_resize_bar=tk.Canvas(frame,height=6,highlightthickness=0,cursor='sb_v_double_arrow')
        self.history_resize_bar.grid(row=3,column=0,sticky='ew',pady=(0,5))
        self.history_resize_bar.bind('<Configure>',lambda _event:self.draw_history_resize_bar())
        self.history_resize_bar.bind('<Button-1>',self.begin_history_resize)
        self.history_resize_bar.bind('<B1-Motion>',self.drag_history_resize)

        self.detail_card=ttk.Frame(frame,style='RoundedCard.TFrame',padding=(8,4))
        self.detail_card.grid(row=4,column=0,sticky='ew',pady=(0,6))
        self.detail_card.columnconfigure(0,weight=1)
        self.details_button = ttk.Button(self.detail_card, text="›  Сведения о работе", style='Detail.Header.TButton',command=self.toggle_details)
        self.details_button.grid(row=0, column=0, sticky="w")
        self.details = ttk.Frame(self.detail_card, style="Card.TFrame", padding=(4,2))
        self.details.columnconfigure(0, weight=1)
        ttk.Label(self.details, textvariable=self.health, style="Card.TLabel",wraplength=420).grid(row=0, column=0, sticky="w", padx=8)
        self.stop_all_button=ttk.Button(self.details,text='F9  Остановить всё',style='Safety.Tool.TButton',
                                      command=getattr(app,'emergency_stop',lambda:None))
        self.stop_all_button.grid(row=0,column=1,rowspan=2,padx=(8,6))
        app.log_toggle_button = ttk.Button(self.details, text="☷  Журнал событий", style="Detail.Tool.TButton", command=app.toggle_logs)
        app.log_toggle_button.grid(row=0, column=2,rowspan=2, sticky="e")
        ttk.Label(self.details,textvariable=self.status,style='MutedCard.TLabel',wraplength=420).grid(row=1,column=0,sticky='w',padx=8,pady=(2,0))
        self.footer = ttk.Frame(frame)
        self.footer.grid(row=6, column=0, sticky='ew', pady=(5, 0))
        self.creator_name = ttk.Label(self.footer, text='casorin', style='Creator.TLabel')
        self.creator_name.pack(side='right')
        self.creator_name.configure(cursor='hand2', takefocus=True)
        self.creator_name.bind('<Button-1>', self.open_creator)
        self.creator_name.bind('<Return>', self.open_creator)
        ttk.Label(self.footer, text='Created by: ', style='Muted.TLabel').pack(side='right')
        self.report_button = ttk.Button(self.footer, text='Сообщить об ошибке', style='Small.TButton', command=self.open_report)
        self.report_button.pack(side='left')
        self.coffee_link = ttk.Label(self.footer, text='на кофе💜', style='Creator.TLabel',
                                     cursor='hand2', takefocus=True)
        self.coffee_link.pack(side='left', padx=(18,0))
        self.coffee_link.bind('<Button-1>', self.open_coffee)
        self.coffee_link.bind('<Return>', self.open_coffee)
        self.coffee_link.bind('<space>', self.open_coffee)
        self.apply_theme()
        app._update_group_table()
        self.update_upper_entry()
        app.start_method_var.trace_add('write', lambda *_: self.update_start_method())
        app.start_method_var.trace_add('write', lambda *_: self.root.after_idle(app.on_start_method_changed))
        self.update_start_method()
        self.pulse()

    def update_daily_reward_warning(self):
        if self.app.mode_var.get():
            if not self.daily_reward_warning.winfo_manager():
                self.daily_reward_warning.pack(pady=(4, 0))
        else:
            self.daily_reward_warning.pack_forget()

    def card(self, parent, expand=False):
        frame = ttk.Frame(parent, style="RoundedCard.TFrame", padding=(12, 4))
        if isinstance(parent, ttk.PanedWindow):
            parent.add(frame, weight=1 if expand else 0)
        else:
            frame.grid(row=self.card_row, column=0, sticky="nsew" if expand else "ew", pady=(0, 8))
        self.card_row += 1
        return frame

    def set_initial_history_size(self, _event=None):
        if getattr(self, '_history_size_set', False):
            return
        self._history_size_set = True
        self.root.after_idle(lambda: self.history_splitter.sashpos(0, self.history_splitter.panes() and
                             self.history_splitter.nametowidget(self.history_splitter.panes()[0]).winfo_reqheight()))

    def draw_history_resize_bar(self):
        c=self.history_resize_bar
        p=PALETTES[self.theme]
        c.configure(bg=p['bg'])
        c.delete('all')
        w=c.winfo_width()
        # Match the compact central grip of the native clam pane divider.
        for x in range(w//2-10,w//2+10,2):
            c.create_line(x,1,x,5,fill='#a0a0a0',width=1)

    def begin_history_resize(self,event):
        self._history_resize_origin=(event.y_root,self.root.winfo_height(),self.history_splitter.sashpos(0))

    def drag_history_resize(self,event):
        origin=getattr(self,'_history_resize_origin',None)
        if origin is None:
            return
        y,height,sash=origin
        target=max(self.root.minsize()[1],height+event.y_root-y)
        self.root.geometry(f'{self.root.winfo_width()}x{target}')
        self.root.update_idletasks()
        self.history_splitter.sashpos(0,sash)

    def open_creator(self, _event=None):
        import webbrowser
        webbrowser.open('https://t.me/casorin')

    def open_coffee(self, _event=None):
        import webbrowser
        webbrowser.open('https://boosty.to/casorin/donate')

    def open_report(self):
        from app.bug_report import ReportWindow
        ReportWindow(self.root, self.app, PALETTES[self.theme])

    def choose_mode(self, enabled):
        if self.app.mode_var.get() == enabled:
            return
        self.app.mode_var.set(enabled)
        self.app._sync_mode()

    def update_upper_entry(self):
        self.upper_entry.configure(state='disabled' if self.app.no_upper_var.get() else 'normal')
        self.draw_range()
        self.draw_history_resize_bar()

    def update_start_method(self):
        percent = self.app.start_method_var.get() == 'percent'
        self.percent_entry.configure(state='normal' if percent else 'disabled')
        if percent:
            self.percent_box.pack(fill='x',pady=(2,4),before=self.settings_separator)
            self.range_entries.pack_forget()
            self.slider.pack_forget()
            self.range_line.pack_forget()
            self.update_percent_preview()
        else:
            self.percent_box.pack_forget()
            self.range_line.pack_forget()
            self.range_entries.pack(fill='x', pady=(2, 2), before=self.settings_separator)
            self.slider.pack(fill='x', pady=(2, 0), before=self.settings_separator)
        self.root.after_idle(self.fit_settings_height)

    def fit_settings_height(self):
        panes=self.history_splitter.panes()
        if panes and self.history_splitter.winfo_ismapped():
            settings=self.history_splitter.nametowidget(panes[0])
            settings.update_idletasks()
            self.history_splitter.sashpos(0,settings.winfo_reqheight())

    def update_percent_preview(self):
        enabled = self.app.percent_floor_enabled_var.get()
        self.percent_floor_entry.configure(state='normal' if enabled else 'disabled')
        try:
            floor = int(self.app.percent_floor_var.get().replace(' ', '').strip()) if enabled else 0
            if floor < 0:
                raise ValueError
        except ValueError:
            self.percent_threshold.set('Укажите минимальный фонд')
            return
        monitor=getattr(self.app,'monitor',None)
        latest=getattr(monitor,'_latest_percentage_reset',None)
        event=latest() if callable(latest) else None
        try:
            percent=int(self.app.start_percent_var.get().strip())
        except ValueError:
            percent=0
        valid=event is not None and type(event.peak_before_reset) is int and event.peak_before_reset>0
        after=getattr(monitor,'_percentage_reference_after',None)
        if valid and after is not None:
            from datetime import datetime
            valid=datetime.fromisoformat(event.timestamp_reset).timestamp()>=after.timestamp()
        if valid and 1<=percent<=100:
            threshold=(event.peak_before_reset*percent+99)//100
            threshold=max(threshold,floor)
            self.percent_threshold.set(f'{threshold:,}'.replace(',',' '))
        else:
            self.percent_threshold.set('Ждём новое обнуление' if 1<=percent<=100 else 'Укажите от 1 до 100%')

    def settings_values(self):
        app=self.app
        def number(variable):
            value=variable.get().replace(' ','').strip()
            try:
                return int(value)
            except ValueError:
                return value
        return (number(app.test_range_min_var),number(app.test_range_max_var),app.no_upper_var.get(),
                app.gem_limit_enabled_var.get(),number(app.gem_floor_var) if app.gem_limit_enabled_var.get() else None,
                app.start_method_var.get(), number(app.start_percent_var),
                number(app.percent_floor_var) if app.percent_floor_enabled_var.get() else None,
                number(app.click_speed_var))

    def update_settings_hint(self):
        pending=self.settings_values()!=self.saved_settings
        self.settings_note.set('Изменения ещё не применены.\nНажмите «Сохранить настройки».' if pending else
            'После изменения нажмите\n«Сохранить настройки».')
        self.settings_hint.configure(style='Pending.TLabel' if pending else 'MutedCard.TLabel')

    def mark_saved(self):
        self.saved_settings=self.settings_values()
        self.settings_note.set('Настройки сохранены.\nВсё готово к наблюдению.')
        self.settings_hint.configure(style='MutedCard.TLabel')

    def toggle_details(self):
        self.details_open = not self.details_open
        if self.details_open:
            self.details.grid(row=1, column=0, sticky="ew")
            self.details_button.configure(text="Сведения о работе",image=self._detail_arrows[1])
        else:
            self.details.grid_remove()
            self.details_button.configure(text="Сведения о работе",image=self._detail_arrows[0])

    def update_empty_history(self):
        items=self.app.history_table.get_children()
        if items and items != ('placeholder',):
            self.empty_history.place_forget()
            return
        p=PALETTES[self.theme]
        c=self.empty_history
        width=self.app.history_table.winfo_width()-18
        height=min(72,max(1,self.app.history_table.winfo_height()-28))
        c.configure(bg=p['card'],width=max(1,width),height=height)
        c.delete('all')
        x=width//2
        if height>=60:
            c.create_rectangle(x-8,3,x+8,18,outline=p['muted'],width=1)
            for y in (7,11,15):
                c.create_line(x-5,y,x+5,y,fill=p['muted'])
        c.create_text(x,32 if height>=60 else 14,text='Обнулений пока нет',fill=p['muted'],font=('Bahnschrift',11,'bold'))
        if height>=60:
            c.create_text(x,52,text='Здесь появятся время, фонд и интервал каждого обнуления.',fill=p['muted'],font=('Bahnschrift',9))
        c.place(x=0,y=28)

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.apply_theme()
        try:
            self.preferences.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.preferences.with_suffix(".tmp")
            temporary.write_text(json.dumps({"theme": self.theme}), encoding="utf-8")
            temporary.replace(self.preferences)
        except OSError:
            self.app._append_log("Не удалось сохранить выбранную тему. Она действует до закрытия окна.")

    def open_help(self):
        if getattr(self, 'help_window', None) is not None and self.help_window.winfo_exists():
            self.help_window.deiconify()
            self.help_window.lift()
            return
        from app.help_window import HelpWindow
        self.help_window = HelpWindow(self.root, PALETTES[self.theme])

    def apply_theme(self):
        p = PALETTES[self.theme]
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure('HeroWarning.TLabel', background=p['hero'],
                    foreground='#c5314b' if self.theme == 'light' else '#ff9aa9',
                    font=('Trebuchet MS', 9))
        if not hasattr(self, "theme_images"):
            self.theme_images = {}
        for role, color in (("Card", p["card"]), ("Hero", p["hero"]), ("Pink", p["pink"]),
                            ("Button",p['card']),('Icon',p['bg']),('Input',p['entry']),('Soft',p['soft'])):
            name = f"Fountain.{self.theme}.{role}"
            if name not in s.element_names():
                outer = p['bg'] if role in {'Card','Hero','Icon'} else p['card']
                size=60 if role in {'Card','Hero','Pink'} else 32
                image = Image.new("RGB", (size, size), outer)
                ImageDraw.Draw(image).rounded_rectangle((0, 0, size-1, size-1), radius=14 if role in {'Card','Hero','Pink'} else 8,
                    fill=color, outline=p['line'] if role in {'Button','Icon','Input'} else color, width=1)
                photo = ImageTk.PhotoImage(image, master=self.root)
                self.theme_images[name] = photo
                s.element_create(name, "image", photo, border=16 if role in {'Card','Hero','Pink'} else 9, sticky="nsew")
            if role in {"Card", "Hero", "Input", "Soft"}:
                style = f"Rounded{role}.TFrame" if role!='Input' else 'Input.TFrame'
                s.layout(style, [(name, {"sticky": "nsew"})])
            else:
                style={'Pink':'Primary.TButton','Button':'TButton','Icon':'Icon.TButton'}[role]
                s.layout(style, [(name, {"sticky": "nsew", "children": [
                    ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
        s.configure(".", font=("Trebuchet MS", 10), background=p["bg"], foreground=p["text"])
        for name, color in (("TFrame", p["bg"]), ("Card.TFrame", p["card"]), ("Hero.TFrame", p["hero"]),('Soft.TFrame',p['soft'])):
            s.configure(name, background=color)
        s.configure("TLabel", background=p["bg"], foreground=p["text"])
        for name, bg, fg, font in (
            ("Title.TLabel", p["bg"], p["text"], ("Trebuchet MS", 17, "bold")),
            ("Muted.TLabel", p["bg"], p["muted"], ("Trebuchet MS", 11)),
            ("Card.TLabel", p["card"], p["text"], ("Trebuchet MS", 11)),
            ("MutedCard.TLabel", p["card"], p["muted"], ("Trebuchet MS", 10)),
            ("Section.TLabel", p["card"], p["text"], ("Trebuchet MS", 15, "bold")),
            ("HeroTitle.TLabel", p["hero"], p["text"], ("Trebuchet MS", 14)),
            ("HeroHint.TLabel", p["hero"], p["muted"], ("Trebuchet MS", 11)),
            ("BigFund.TLabel", p["hero"], p["text"], ("Segoe UI Black", 32, "bold")),
            ("Stat.TLabel", p["hero"], p["text"], ("Trebuchet MS", 20, "bold")),
            ("Badge.TLabel", p["green"], p["text"], ("Trebuchet MS", 10)),
            ('SoftHint.TLabel',p['soft'],p['muted'],('Bahnschrift',11)),
            ('SoftStat.TLabel',p['soft'],p['text'],('Bahnschrift',17,'bold'))):
            s.configure(name, background=bg, foreground=fg, font=font)
        s.configure('Threshold.TLabel',background=p['soft'],foreground=p['text'],font=('Bahnschrift',18,'bold'))
        s.configure('Percent.TLabel',background=p['entry'],foreground=p['muted'],font=('Bahnschrift',14,'bold'))
        s.configure('WalletValue.TLabel',background=p['card'],foreground=p['text'],font=('Bahnschrift',13,'bold'))
        s.configure('Save.TButton',font=('Trebuchet MS',10),padding=(8,0))
        s.configure('Wallet.Card.TCheckbutton',font=('Trebuchet MS',11),background=p['card'],foreground=p['text'])
        s.configure('SettingsSection.TLabel',background=p['card'],foreground=p['text'],font=('Trebuchet MS',17,'bold'))
        s.layout('TSeparator',[('Separator.separator',{'sticky':'nswe'})])
        s.configure('TSeparator',background=p['line'],borderwidth=0)
        s.configure('Pending.TLabel',background=p['card'],foreground='#9a580b' if self.theme=='light' else '#ffd28d',font=('Bahnschrift',10,'bold'))
        s.configure("TButton", background=p["card"], foreground=p["text"], bordercolor=p["line"], lightcolor=p["line"], darkcolor=p["line"], padding=(12, 0))
        s.map("TButton", background=[("active", p["hero"])], foreground=[("active", p["text"])])
        s.configure("Small.TButton", padding=(8, 0))
        s.configure('Restart.TButton',font=('Bahnschrift',18,'bold'),padding=(10,0))
        s.configure('Icon.TButton',font=('Segoe UI Symbol',18),padding=(2,0))
        s.layout('Top.TButton',s.layout('Icon.TButton'))
        s.configure('Top.TButton',font=('Trebuchet MS',10),padding=(8,5),foreground=p['text'])
        s.configure('Window.TCombobox',fieldbackground=p['entry'],background=p['entry'],foreground=p['text'],
                    arrowcolor=p['muted'],borderwidth=0,bordercolor=p['entry'],lightcolor=p['entry'],darkcolor=p['entry'],padding=2)
        s.map('Window.TCombobox',fieldbackground=[('readonly',p['entry'])],foreground=[('readonly',p['text'])],
              selectbackground=[('readonly',p['entry'])],selectforeground=[('readonly',p['text'])])
        for name in ('Log.Tool.TButton','Detail.Tool.TButton','Safety.Tool.TButton'):
            s.configure(name,font=('Bahnschrift',9,'bold' if name=='Safety.Tool.TButton' else 'normal'),padding=(6,1))
        s.configure('Log.Tool.TButton',font=('Bahnschrift',8),padding=(3,0))
        s.layout('Detail.Header.TButton',[('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})])
        s.configure('Detail.Header.TButton',background=p['card'],foreground=p['text'],font=('Bahnschrift',11,'bold'),padding=(2,2),anchor='w')
        arrow_key=f'Fountain.{self.theme}.DetailArrows'
        if arrow_key not in self.theme_images:
            self.theme_images[arrow_key]=[]
            for opened in (False,True):
                image=Image.new('RGB',(20,18),p['card'])
                pen=ImageDraw.Draw(image)
                pen.line((5,5,10,10,15,5) if opened else (7,3,12,8,7,13),fill=p['text'],width=2)
                self.theme_images[arrow_key].append(ImageTk.PhotoImage(image,master=self.root))
        self._detail_arrows=self.theme_images[arrow_key]
        self.details_button.configure(text='Сведения о работе',image=self._detail_arrows[int(self.details_open)],compound='left')
        safety_element=f'Fountain.{self.theme}.Safety'
        if safety_element not in s.element_names():
            im=Image.new('RGB',(32,32),p['card'])
            ImageDraw.Draw(im).rounded_rectangle((0,0,31,31),radius=7,fill='#fff0f6' if self.theme=='light' else '#463149',outline=p['pink'])
            self.theme_images[safety_element]=ImageTk.PhotoImage(im,master=self.root)
            s.element_create(safety_element,'image',self.theme_images[safety_element],border=9,sticky='nsew')
        s.layout('Safety.Tool.TButton',[(safety_element,{'sticky':'nsew','children':[
            ('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})]})])
        s.layout('Help.Icon.TButton', s.layout('Icon.TButton'))
        s.configure('Help.Icon.TButton', font=('Segoe UI Symbol', 22), foreground=p['pink'], padding=(2,0))
        s.map('Help.Icon.TButton', foreground=[('active',p['pink'])])
        s.configure('Creator.TLabel', background=p['bg'], foreground=p['pink'], font=('Trebuchet MS',11,'bold'))
        if getattr(self, 'help_window', None) is not None and self.help_window.winfo_exists():
            self.help_window.apply_palette(p)
        s.configure('Card.TCheckbutton',background=p['card'],foreground=p['text'])
        s.map('Card.TCheckbutton',background=[('active',p['card'])])
        check_name=f'Fountain.{self.theme}.Check'
        if check_name not in s.element_names():
            images=[]
            for selected in (False,True):
                im=Image.new('RGB',(20,20),p['card'])
                pen=ImageDraw.Draw(im)
                pen.rounded_rectangle((1,1,18,18),radius=4,fill=p['pink'] if selected else p['entry'],outline=p['pink'])
                if selected:
                    pen.line((5,10,9,14,15,6),fill='#101a4b',width=2)
                images.append(ImageTk.PhotoImage(im,master=self.root))
            self.theme_images[check_name]=images
            s.element_create(check_name,'image',images[0],('selected',images[1]),sticky='')
        s.layout('Card.TCheckbutton',[(check_name,{'side':'left'}),('Checkbutton.padding',{'sticky':'nsew','children':[
            ('Checkbutton.label',{'sticky':'nsew'})]})])
        wallet_check = f'Fountain.{self.theme}.WalletCheck'
        if wallet_check not in s.element_names():
            images=[]
            for selected in (False,True):
                im=Image.new('RGB',(30,30),p['card'])
                pen=ImageDraw.Draw(im)
                pen.rounded_rectangle((1,1,28,28),radius=6,fill=p['pink'] if selected else p['entry'],outline=p['pink'])
                if selected:
                    pen.line((7,15,13,21,24,8),fill='white',width=3)
                images.append(ImageTk.PhotoImage(im,master=self.root))
            self.theme_images[wallet_check]=images
            s.element_create(wallet_check,'image',images[0],('selected',images[1]),sticky='')
        s.layout('Wallet.Card.TCheckbutton',[(wallet_check,{'side':'left'}),('Checkbutton.padding',{'sticky':'nsew','children':[
            ('Checkbutton.label',{'sticky':'nsew'})]})])
        s.configure('SmallWallet.Card.TCheckbutton', background=p['card'], foreground=p['text'],
                    font=('Trebuchet MS',9))
        s.map('SmallWallet.Card.TCheckbutton', background=[('active',p['card'])])
        small_check = f'Fountain.{self.theme}.SmallWalletCheck'
        if small_check not in s.element_names():
            images=[]
            for selected in (False,True):
                im=Image.new('RGB',(16,16),p['card'])
                pen=ImageDraw.Draw(im)
                pen.rounded_rectangle((1,1,14,14),radius=3,
                                      fill=p['pink'] if selected else p['entry'],outline=p['pink'])
                if selected:
                    pen.line((4,8,7,11,12,4),fill='white',width=2)
                images.append(ImageTk.PhotoImage(im,master=self.root))
            self.theme_images[small_check]=images
            s.element_create(small_check,'image',images[0],('selected',images[1]),sticky='')
        s.layout('SmallWallet.Card.TCheckbutton',[(small_check,{'side':'left'}),
            ('Checkbutton.padding',{'sticky':'nsew','children':[('Checkbutton.label',{'sticky':'nsew'})]})])
        for name in ("Primary.TButton", "Selected.TButton"):
            s.configure(name, background=p["pink"], foreground="#141b45", bordercolor=p["pink"], padding=(18, 4))
            s.map(name, background=[("active", p["hover"])], foreground=[("active", "#141b45")])
        s.configure("Primary.TButton", font=("Segoe UI Black", 22, "bold"))
        s.configure("Primary.TButton", padding=(18, 0))
        s.configure("TSpinbox", fieldbackground=p["entry"], foreground=p["text"], arrowcolor=p["muted"], borderwidth=0, bordercolor=p["entry"], lightcolor=p["entry"], darkcolor=p["entry"])
        s.configure('TEntry',fieldbackground=p['entry'],foreground=p['text'],borderwidth=0,bordercolor=p['entry'],lightcolor=p['entry'],darkcolor=p['entry'])
        s.map("TSpinbox", fieldbackground=[("readonly", p["entry"])])
        s.configure("Treeview", background=p["card"], fieldbackground=p["card"], foreground=p["text"], rowheight=28, borderwidth=0, font=("Trebuchet MS", 11))
        s.configure("Treeview.Heading", background=p["soft"], foreground=p["muted"], font=("Trebuchet MS", 10, "bold"), padding=(6, 4))
        s.layout('Treeview.Heading', [('Treeheading.cell',{'sticky':'nswe'}),
            ('Treeheading.padding',{'sticky':'nswe','children':[('Treeheading.text',{'sticky':'we'})]})])
        s.configure('Treeview',bordercolor=p['card'],lightcolor=p['card'],darkcolor=p['card'])
        s.map("Treeview", background=[("selected", p["hero"])], foreground=[("selected", p["text"])])
        self.root.configure(bg=p["bg"])
        self.slider.configure(bg=p["card"])
        self.app.history_table.tag_configure("newest", background=p["row"])
        self.app.log.configure(bg=p["card"], fg=p["text"], insertbackground=p["text"], relief="flat")
        self.app.log.configure(font=('Consolas',10),padx=6,pady=6)
        self.app.log_panel.scrollbar.configure(bg=p['card'])
        self.history_scrollbar.configure(bg=p['card'])
        self.update_empty_history()
        self.theme_label.set("☾" if self.theme == "light" else "☀")
        self.mode_switch.palette=p
        self.mode_switch.draw()
        self.start_rule_switch.palette=p
        self.start_rule_switch.draw()
        for widget in (self.threshold_card,self.start_button,self.restart_button):
            widget.palette=p
            widget.draw()
        self.badge.palette=p
        self.badge.draw()
        self.draw_range()

    def draw_range(self):
        if not hasattr(self, "slider"):
            return
        c = self.slider
        p = PALETTES[self.theme]
        c.delete("all")
        width = max(200, c.winfo_width())
        start, end = 45, width - 70
        try:
            low = max(1000, min(999999, int(self.app.test_range_min_var.get().replace(" ", ""))))
            high = max(1000, min(999999, int(self.app.test_range_max_var.get().replace(" ", ""))))
        except ValueError:
            return
        x1, x2 = start + low / 1000000 * (end-start), start + high / 1000000 * (end-start)
        if self.app.no_upper_var.get():
            x2=end
        c.create_line(start, 18, end, 18, fill=p["line"], width=8, capstyle="round")
        c.create_line(x1, 18, x2, 18, fill="#68bde9", width=8, capstyle="round")
        for x, value in ((x1, low), (x2, high)):
            c.create_oval(x-10, 8, x+10, 28, fill=p["pink"], outline=p["card"], width=3)
            label='без предела' if x==x2 and self.app.no_upper_var.get() else f"{value:,}".replace(",", " ")
            c.create_text(x, 38, text=label, fill=p["text"], font=("Trebuchet MS", 10))
        c.create_text(10, 18, text="0", fill=p["muted"], anchor="w")
        c.create_text(width-2, 18, text="1 млн", fill=p["muted"], anchor="e")

    def begin_drag(self, event):
        width = max(200, self.slider.winfo_width())
        try:
            points = [45 + int(v.get().replace(" ", "")) / 1000000 * (width-115) for v in (self.app.test_range_min_var, self.app.test_range_max_var)]
        except ValueError:
            return
        self.dragging = 0 if self.app.no_upper_var.get() or abs(event.x-points[0]) < abs(event.x-points[1]) else 1
        self.drag_range(event)

    def drag_range(self, event):
        if self.dragging is None:
            return
        width = max(200, self.slider.winfo_width())
        value = max(1000, min(999999, round((event.x-45)/(width-115)*1000000/500)*500))
        variables = (self.app.test_range_min_var, self.app.test_range_max_var)
        try:
            other = int(variables[1-self.dragging].get().replace(" ", ""))
        except ValueError:
            return
        value = min(value, other-1) if self.dragging == 0 else max(value, other+1)
        variables[self.dragging].set(str(value))

    def pulse(self):
        self.update_percent_preview()
        app = self.app
        if hasattr(app, 'monitor') and hasattr(app.monitor, 'state'):
            from app.user_guidance import observation_help
            self.action_guidance.set(observation_help(app))
            self.guidance_label.grid()
        self.update_empty_history()
        phase = app.phase_var.get()
        labels = {"WAITING": "Ждём подходящую сумму", "CANDIDATE": "Проверяем сумму",
                  "CONFIRMED": "Сумма подтверждена", "ACTIVE_CLICKING": "Загадываем желания" if app.mode_var.get() else "Проверяем работу без расходов",
                  "CHECKING_AFTER_BURST": "Проверяем призовой фонд", "RESET_COOLDOWN": "После обнуления ждём: " + app.cooldown_var.get(),
                  "RESET_TIME_UNKNOWN": "Знакомимся с текущим событием. Сначала наблюдаем 2 минуты",
                  "PAUSED": "На паузе", "EMERGENCY_STOP": "Остановлено. Настоящие клики выключены", "LOCKED": "Ждём нового цикла"}
        self.status.set(labels.get(phase, "Готово к работе"))
        self.health.set(" · ".join(("Игра подключена" if "Подключено" in app.connection_var.get() or "connected" in app.connection_var.get() else "Проверьте подключение",
                                   "Экран найден" if app.screen_var.get().startswith("подтверждён") else "Откройте событие",
                                   "Кнопка найдена" if app.button_var.get().startswith("подтверждена") else "Проверяем кнопку")))
        visibility = app.ocr_var.get()
        self.visibility.set("Число временно закрыто" if "Закрыто" in visibility else "Не удалось прочитать" if "Ошибка" in visibility or "timeout" in visibility else visibility)
        p = PALETTES[self.theme]
        warmup_failed = bool(getattr(app, 'ocr_warmup_error', None))
        preparing = hasattr(app, 'ocr_warmup_complete') and not app.ocr_warmup_complete and not warmup_failed
        self.start_button.configure(text="Повторить / F8" if warmup_failed else "Готовим / F8" if preparing else "Остановить / F8" if app.running else "Начать / F8")
        if preparing:
            self.visibility.set('Готовим программу…')
        elif warmup_failed:
            self.visibility.set('Ошибка подготовки')
            self.status.set('Подготовка не завершилась. Нажмите «Повторить».')
        balance_text=app.gem_balance_var.get().replace('Баланс: ','')
        self.wallet_value.set('Пока не прочитан' if not balance_text or 'не удалось' in balance_text or 'проверяем' in balance_text else balance_text)
        if self.mode_switch.selected!=app.mode_var.get():
            self.mode_switch.selected=app.mode_var.get()
            self.mode_switch.draw()
        if hasattr(app,'monitor') and hasattr(app.monitor,'gem_guard'):
            balance=app.monitor.gem_guard.balance
            app.gem_balance_var.set('Баланс: '+(f'{balance:,}'.replace(',',' ') if balance is not None else 'не удалось прочитать'))
        bbox=app.history_table.bbox('event-0','time') if app.history_table.exists('event-0') else ()
        if bbox:
            x,y,w,h=bbox
            self.latest_badge.configure(bg=p['row'])
            self.latest_badge.delete('all')
            rounded(self.latest_badge,0,0,99,25,12,fill=p['green'],outline='')
            self.latest_badge.create_text(50,13,text='Последнее',fill=p['text'],font=('Bahnschrift',10))
            self.latest_badge.place(x=x+116,y=y+(h-26)//2)
        else:
            self.latest_badge.place_forget()
        self.root.after(250, self.pulse)
