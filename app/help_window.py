"""Player-facing guide; opening it never changes monitor settings or mode."""
import tkinter as tk
from tkinter import ttk


GUIDE = (
    ("Первый запуск", "Первый запуск\n\n1. Откройте Kingdom Guard в эмуляторе и перейдите в фонтан. На экране должны быть видны призовой фонд и кнопка «Загадать желание».\n\n2. В кликере нажмите «Выбрать окно эмулятора». Посмотрите снимок и отметьте нужный аккаунт.\n\nЕсли нужного окна нет в списке:\n\nДождитесь полной загрузки эмулятора и нажмите «Обновить снимки».\n\nВ LDPlayer: шестерёнка → «Другие настройки» → «Отладка ADB» → «Открыть локальное подключение» → сохранить.\n\nВ BlueStacks: шестерёнка → «Дополнительно» → «Android Debug Bridge (ADB)» → включить → сохранить.\n\nЭто нужно сделать в каждом используемом окне. Если эмулятор попросит перезапуск, перезапустите его. Затем снова обновите снимки и выберите нужное окно.\n\n3. Настройте, при какой сумме начинать клики. При необходимости укажите запас самоцветов.\n\n4. Нажмите «Сохранить настройки».\n\n5. Выберите «Без кликов» и нажмите «Начать». Проверьте, что программа правильно показывает фонд.\n\n6. Когда всё готово, выберите «С кликами» и подтвердите включение.\n\nВ режиме «С кликами» программа расходует самоцветы. Выигрыш не гарантирован."),
    ("Когда начинать клики", "Когда начинать клики\n\nПо сумме — задайте нижнюю и верхнюю границы. Например, от 80 000 до 200 000. Чтобы оставить только нижнюю границу, включите «Без верхнего предела».\n\nПо прошлому фонду — укажите процент от суммы перед последним записанным обнулением. Например, если фонд был 100 000, при значении 80% клики начнутся от 80 000. Справа показана рассчитанная сумма.\n\nЕсли подходящего обнуления ещё нет, программа сначала ждёт его. После обнуления нужно подождать 2 минуты, затем — достижения выбранной суммы.\n\nВерхняя граница определяет момент начала серии. Если во время кликов фонд вырос выше неё, серия может продолжаться до обнуления или остановки по другим условиям.\n\nПосле изменения любого значения нажимайте «Сохранить настройки»."),
    ("Начать и остановить", "Начать и остановить\n\n«Начать / Остановить» или F8 — запустить или приостановить наблюдение. Если открыто несколько окон кликера, F8 переключает работу каждого из них.\n\nПри включении «С кликами» программа учитывает подтверждённое время в «После обнуления». До 2 минут она ждёт только оставшееся время. От 2 до 15 минут клики могут начаться по вашему правилу после свежей проверки фонда, кнопки и баланса. Если прошло больше 15 минут или время обнуления неизвестно, программа ждёт новое обнуление. Переключение режима не запускает дополнительные 2 минуты ожидания.\n\nF9 — «Остановить всё» — срочно остановить все окна кликера и выключить настоящие клики.\n\nОбе клавиши работают, даже если открыта другая программа. После остановки проверяйте режим перед возобновлением кликов.\n\n«Ждать новое обнуление» — сбросить текущий период и заново дождаться обнуления. Кликовый режим выключится, старый таймер исчезнет. История и настройки сохранятся. Эта кнопка не обнуляет фонд в игре."),
    ("Как сохранить запас самоцветов", "Как сохранить запас самоцветов\n\nВключите «Оставить на счёте», впишите нужную сумму и нажмите «Сохранить настройки».\n\nНапример, при запасе 40 000 программа прекратит желания, когда следующий клик уже не позволит сохранить эту сумму. Баланс проверяется отдельно на каждом аккаунте.\n\nЕсли галочка выключена, ограничение запаса не действует."),
    ("Несколько аккаунтов", "Несколько аккаунтов\n\nВ «Выбрать окно эмулятора» можно отметить несколько аккаунтов. Настройки будут общими для выбранных окон.\n\nВ одном окне кликера выбирайте только аккаунты с одинаковым призовым фондом. Для другого фонда нажмите «Доп. окно программы» и настройте его отдельно.\n\nФонд и время ожидания общие: программа читает фонд из первого окна в выбранном списке. Оставляйте в этом окне открытый фонтан. В остальных аккаунтах отдельно проверяются экран, кнопка желания и запас самоцветов.\n\nЕсли в одном из остальных окон открыт не фонтан, кликов в нём не будет, а подходящие окна могут продолжать работу. Если фонд в первом окне не читается или оно закрыто, клики во всех окнах ждут свежих данных."),
    ("История обнулений", "История обнулений\n\nКаждая строка — обнуление, которое программа заметила и подтвердила:\n\n• Время — когда произошло обнуление.\n• Фонд перед обнулением — последнее подтверждённое значение перед падением.\n• Интервал — сколько прошло между этим и предыдущим обнулением.\n\nСамая новая запись находится сверху и отмечена «Последнее». Если показано «Неизвестно», данных для расчёта интервала не хватает.\n\n«После обнуления» показывает прошедшее время, а «Средний интервал» — среднее время между записанными обнулениями.\n\n«Очистить историю» удаляет записи после подтверждения. Для нового периода наблюдения используйте «Ждать новое обнуление», а не очистку истории.\n\nЧтобы увеличить таблицу, потяните разделитель над ней. Нижняя ручка увеличивает историю вместе с окном программы."),
    ("Эмуляторы и разрешение", "Эмуляторы и разрешение\n\nДля режима «С кликами» рекомендуемое разрешение: 1080 × 1080.\n\nПодключение и чтение проверены на MEmu, LDPlayer 14 и BlueStacks 5 с русским интерфейсом игры.\n\nПроверенные разрешения: MEmu — 1080 × 1080 и 720 × 1280; LDPlayer и BlueStacks — 1080 × 1080 и 1080 × 1920.\n\nРазрешение задаётся в настройках эмулятора. Простое растягивание окна на рабочем столе его не меняет. Другие размеры сначала проверяйте в режиме «Без кликов»."),
    ("Если программа не работает", "Если программа не работает\n\nЕсли фонд не читается, проверьте, что открыт фонтан и цифры не закрыты всплывающим окном. Надпись «Не проверено» означает, что свежих показаний пока нет.\n\nЕсли клики не начинаются, проверьте: включён ли режим «С кликами», сохранены ли настройки, прошло ли 2 минуты после обнуления и достигнута ли нужная сумма.\n\nЕсли окно зависло или появилось сообщение об ошибке, нажмите F9. Перезапустите проблемный эмулятор и сначала проверьте работу без кликов.\n\nЕсли проблема повторяется, нажмите «Сообщить об ошибке» → «Открыть форму с отчётом». Напишите, что вы нажали и что произошло вместо ожидаемого. По возможности добавьте снимок экрана и контакт для ответа."),
)


class TopicNavigation(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, width=250, highlightthickness=0, takefocus=True, cursor='hand2')
        self.selected = 0
        self.palette = {}
        self.rows = []
        self.bind('<Configure>', lambda _: self.draw())
        self.bind('<Button-1>', self.choose)
        self.bind('<Down>', lambda _: self.select_relative(1))
        self.bind('<Up>', lambda _: self.select_relative(-1))
        self.bind('<MouseWheel>', lambda event: self.yview_scroll(-int(event.delta/120), 'units'))

    def selection_set(self, index):
        self.selected = index
        self.draw()

    def curselection(self):
        return (self.selected,)

    def select_relative(self, delta):
        self.selection_set(max(0, min(len(GUIDE)-1, self.selected+delta)))
        self.event_generate('<<ListboxSelect>>')

    def choose(self, event):
        y = self.canvasy(event.y)
        for index, (top, bottom) in enumerate(self.rows):
            if top <= y <= bottom:
                self.selection_set(index)
                self.event_generate('<<ListboxSelect>>')
                break

    def draw(self):
        if not self.palette:
            return
        from app.ui_design import rounded
        p = self.palette
        self.configure(bg=p['bg'])
        self.delete('all')
        width = max(180, self.winfo_width())
        y = 10
        self.rows = []
        for index, (title, _) in enumerate(GUIDE):
            item = self.create_text(22, y+16, text=title, anchor='nw', width=width-40,
                                    fill=p['text'], font=('Trebuchet MS', 12,
                                    'bold' if index == self.selected else 'normal'))
            box = self.bbox(item)
            height = max(56, box[3]-box[1]+32)
            if index == self.selected:
                fill = '#fbd9e6' if p['card'] == '#ffffff' else '#493342'
                panel = rounded(self, 5, y, width-5, y+height, 12, fill=fill, outline='')
                self.tag_lower(panel, item)
                self.create_line(8, y+8, 8, y+height-8, fill=p['pink'], width=5, capstyle='round')
            self.rows.append((y, y+height))
            y += height+8
        self.configure(scrollregion=(0, 0, width, y))


class GuideCard(tk.Canvas):
    def __init__(self, parent, paragraph, palette, scroll):
        import re
        super().__init__(parent, highlightthickness=0, bg=palette['card'], height=70)
        self.palette = palette
        self.step = re.match(r'^(\d+)\.\s+', paragraph)
        self.recommendation = paragraph.startswith('Для режима «С кликами» рекомендуемое разрешение:')
        self.callout = self.recommendation or paragraph.startswith(('В LDPlayer:', 'В BlueStacks:'))
        self.note = paragraph.startswith('Это нужно сделать')
        self.heading = paragraph.endswith(':') and not self.callout
        self.left = 72 if self.step else 24 if self.callout else 16
        content = paragraph[self.step.end():] if self.step else paragraph
        self.content = content
        self.body = tk.Text(self, wrap='word', font=('Trebuchet MS', 12, 'bold' if self.heading or self.recommendation else 'normal'),
                            borderwidth=0, highlightthickness=0, padx=0, pady=0, height=1,
                            spacing1=2, spacing3=3, cursor='arrow')
        self.body.insert('1.0', content)
        self.body.tag_configure('button', font=('Trebuchet MS', 12, 'bold'),
                                background='#ffe0ec' if palette['card'] == '#ffffff' else '#533747')
        for match in re.finditer(r'«[^»]+»', content):
            self.body.tag_add('button', f'1.0+{match.start()}c', f'1.0+{match.end()}c')
        if self.callout:
            self.body.tag_configure('emulator', font=('Trebuchet MS', 12, 'bold'))
            self.body.tag_add('emulator', '1.0', f'1.0+{content.index(":")}c')
        self.body.configure(state='disabled')
        self.body.bind('<MouseWheel>', scroll)
        self.bind('<MouseWheel>', scroll)
        self.window = self.create_window(self.left, 16, anchor='nw', window=self.body)
        self._width = 0

    def set_width(self, width):
        if width == self._width:
            return
        self._width = width
        self.configure(width=width)
        self.itemconfigure(self.window, width=max(100, width-self.left-18))
        self.after_idle(self.resize_body)

    def resize_body(self):
        if not self.winfo_exists():
            return
        import tkinter.font as font
        # Off-screen embedded widgets have no reliable display-line count.
        # Measure against the requested width rather than their mapped geometry.
        measure = font.Font(font=('Trebuchet MS', 12, 'bold'))
        available = max(100, self._width-self.left-18)
        lines = 0
        for paragraph in self.content.split('\n'):
            used = 0
            lines += 1
            for word in paragraph.split():
                size = measure.measure(word+' ')
                if used and used+size > available:
                    lines += 1
                    used = 0
                used += size
        self.body.configure(height=lines)
        height = max(66 if self.step else 42, lines*(font.Font(font=self.body.cget('font')).metrics('linespace')+5)+32)
        self.configure(height=height)
        self.draw(height)

    def draw(self, height):
        from app.ui_design import rounded
        p = self.palette
        light = p['card'] == '#ffffff'
        fill = ('#fff7fa' if light else '#352c3b') if self.step else p['soft'] if self.callout else (
                '#ffe7ef' if light else '#493342') if self.note else p['card']
        self.body.configure(bg=fill, fg=p['text'])
        self.delete('decoration')
        panel = rounded(self, 1, 1, self._width-1, height-1, 12, fill=fill,
                        outline=p['pink'] if self.step or self.recommendation else '', tags='decoration')
        self.tag_lower(panel)
        if self.step:
            self.create_oval(16, 20, 56, 60, fill=p['pink'], outline='', tags='decoration')
            self.create_text(36, 40, text=self.step.group(1), fill=p['text'],
                             font=('Trebuchet MS', 14, 'bold'), tags='decoration')
        if self.callout:
            self.create_line(4, 12, 4, height-12, fill=p['pink'], width=6, capstyle='round', tags='decoration')


class HelpWindow(tk.Toplevel):
    def __init__(self, parent, palette):
        super().__init__(parent)
        from app.window_picker import PinkScrollbar
        self.title('Как пользоваться кликером')
        self.transient(parent)
        width = min(1100, self.winfo_screenwidth()-80)
        height = min(820, self.winfo_screenheight()-100)
        self.geometry(f'{width}x{height}')
        self.minsize(min(840, width), min(540, height))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.cards = []
        self.heading = tk.Label(self, text='Всё просто. Давайте разберёмся.', anchor='w',
                                font=('Trebuchet MS', 24, 'bold'), padx=24, pady=20)
        self.heading.grid(row=0, column=0, sticky='ew')
        self.body_frame = tk.Frame(self, padx=18)
        self.body_frame.grid(row=1, column=0, sticky='nsew')
        self.body_frame.columnconfigure(1, weight=1)
        self.body_frame.rowconfigure(0, weight=1)
        self.topics = TopicNavigation(self.body_frame)
        self.topics.grid(row=0, column=0, sticky='ns', padx=(0, 16))
        self.article = tk.Frame(self.body_frame, padx=14, pady=10, highlightthickness=1)
        self.article.grid(row=0, column=1, sticky='nsew')
        self.article.columnconfigure(0, weight=1)
        self.article.rowconfigure(0, weight=1)
        self.text = tk.Text(self.article, wrap='word', font=('Trebuchet MS', 12), padx=8, pady=8,
                            spacing3=12, borderwidth=0, highlightthickness=0, cursor='arrow')
        self.text.grid(row=0, column=0, sticky='nsew')
        self.scrollbar = PinkScrollbar(self.article, self.text.yview, palette['card'])
        self.scrollbar.grid(row=0, column=1, sticky='ns')
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.bind('<Configure>', self.resize_cards)
        self.footer = tk.Frame(self, padx=18, pady=12)
        self.footer.grid(row=2, column=0, sticky='ew')
        self.close_button = tk.Button(self.footer, text='Понятно', command=self.destroy,
                                      font=('Trebuchet MS', 12), relief='flat', borderwidth=0,
                                      padx=24, pady=8, cursor='hand2')
        self.close_button.pack(side='right')
        self.topics.bind('<<ListboxSelect>>', self.show_topic)
        self.bind('<Escape>', lambda _: self.destroy())
        self.apply_palette(palette)

    def apply_palette(self, palette):
        palette = dict(palette)
        if palette['card'] == '#ffffff':
            palette.update(bg='#d9efff', soft='#d3ecff', line='#93c8ed')
        else:
            palette.update(bg='#172942', soft='#243e5a', line='#477398')
        self.palette = palette
        self.configure(bg=palette['bg'])
        self.heading.configure(bg=palette['bg'], fg=palette['text'])
        self.body_frame.configure(bg=palette['bg'])
        self.footer.configure(bg=palette['bg'])
        self.article.configure(bg=palette['card'], highlightbackground=palette['line'])
        self.topics.palette = palette
        self.topics.draw()
        self.text.configure(bg=palette['card'], fg=palette['text'], insertbackground=palette['text'])
        self.text.tag_configure('title', font=('Trebuchet MS', 23, 'bold'), foreground=palette['text'])
        self.scrollbar.configure(bg=palette['card'])
        self.close_button.configure(bg=palette['pink'], fg=palette['text'],
                                    activebackground=palette['hover'], activeforeground=palette['text'])
        self.show_topic()

    def scroll_article(self, event):
        self.text.yview_scroll(-int(event.delta/120), 'units')
        return 'break'

    def resize_cards(self, _event=None):
        width = max(200, self.text.winfo_width()-24)
        for card in self.cards:
            card.set_width(width)

    def show_topic(self, _event=None):
        selected = self.topics.curselection()
        if not selected:
            return
        for card in self.cards:
            card.destroy()
        self.cards = []
        content = GUIDE[selected[0]][1]
        title, _, body = content.partition('\n')
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('end', title+'\n', 'title')
        for paragraph in body.strip().split('\n\n'):
            card = GuideCard(self.text, paragraph, self.palette, self.scroll_article)
            self.cards.append(card)
            self.text.window_create('end', window=card)
            self.text.insert('end', '\n')
        self.text.configure(state='disabled')
        self.resize_cards()
        self.text.yview_moveto(0)
