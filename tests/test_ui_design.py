import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app.ui_design import FountainDesign, load_theme
from app.ui import AppWindow
from app.monitor import MonitorState


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.geometry('1100x980+10000+10000')
        names = ('connection value status phase mode_label mode_banner range tap_policy confirmations screen button ocr '
                 'last_reset since_reset cooldown active_burst total_taps reset_since reset_average reset_min '
                 'reset_max active_range test_range_min test_range_max log_toggle window_label').split()
        app = SimpleNamespace(root=self.root, config=SimpleNamespace(runtime_dir=Path(self.directory.name)), running=False)
        for name in names:
            setattr(app, name+'_var', tk.StringVar(self.root, value=''))
        app.phase_var.set('WAITING')
        app.test_range_min_var.set('60000')
        app.test_range_max_var.set('500000')
        app.mode_var = tk.BooleanVar(self.root, value=False)
        app.no_upper_var=tk.BooleanVar(self.root,value=False)
        app.gem_limit_enabled_var=tk.BooleanVar(self.root,value=False)
        app.gem_floor_var=tk.StringVar(self.root,value='40000')
        app.gem_balance_var=tk.StringVar(self.root,value='')
        for name in ('toggle', 'reset_lock', 'apply_range', 'clear_all_history', 'delete_selected_history_entry', 'toggle_logs', '_sync_mode', '_append_log', 'choose_window', '_focus_session', '_update_group_table', 'open_program_window','emergency_stop'):
            setattr(app, name, Mock())
        app.on_start_method_changed = Mock()
        self.app = app
        self.design = FountainDesign(app)
        self.root.update()

    def test_other_program_window_button_visible_and_opens_dialog(self):
        button = self.app.other_program_button
        self.assertTrue(button.winfo_viewable())
        self.assertLessEqual(button.winfo_x() + button.winfo_width(), button.master.winfo_width())
        button.invoke()
        self.app.open_program_window.assert_called_once()

    def test_daily_reward_warning_is_under_mode_switch_and_matches_theme(self):
        from tkinter import ttk
        warning = self.design.daily_reward_warning
        self.assertEqual('Рекомендуемое разрешение: 1080 × 1080.', warning.cget('text'))
        self.assertIn('1080 × 1080', warning.cget('text'))
        self.assertFalse(warning.winfo_viewable())
        self.app.mode_var.set(True)
        self.root.update()
        self.assertTrue(warning.winfo_viewable())
        self.assertGreaterEqual(warning.winfo_y(), self.design.mode_switch.winfo_height())
        self.assertLessEqual(warning.winfo_width(), 300)
        style = ttk.Style(self.root)
        self.assertEqual(style.lookup('HeroWarning.TLabel', 'foreground'), '#c5314b')
        self.design.toggle_theme()
        self.root.update()
        self.assertEqual(style.lookup('HeroWarning.TLabel', 'foreground'), '#ff9aa9')
        self.app.mode_var.set(False)
        self.root.update()
        self.assertFalse(warning.winfo_viewable())
        self.assertEqual(warning.winfo_manager(), '')

    def test_additional_window_launches_directly_with_unique_profile(self):
        with patch('app.ui.subprocess.Popen') as launch, patch('app.ui.tk.Toplevel') as dialog:
            AppWindow.open_program_window(self.app)
            AppWindow.open_program_window(self.app)
        dialog.assert_not_called()
        self.assertEqual(launch.call_count,2)
        first,second=launch.call_args_list
        self.assertEqual(first.args[0][1:4],['-m','app.ui','--profile'])
        self.assertNotEqual(first.args[0][4],second.args[0][4])
        self.assertEqual(Path(first.kwargs['cwd']),Path(__file__).resolve().parents[1])

    def test_additional_window_launch_error_is_shown_in_main_window(self):
        with (patch('app.ui.subprocess.Popen',side_effect=OSError('launch failed')),
              patch('app.ui.messagebox.showerror') as error):
            AppWindow.open_program_window(self.app)
        error.assert_called_once_with('Не удалось открыть окно','launch failed',parent=self.root)

    def test_history_headers_match_value_alignment_and_reset_label_is_explicit(self):
        for column in ('time','peak','interval'):
            self.assertEqual(str(self.app.history_table.heading(column,'anchor')),
                             str(self.app.history_table.column(column,'anchor')))
        self.assertEqual(str(self.app.history_table.column('peak','anchor')),'center')
        self.assertIn('Ждать новое',self.design.restart_button.cget('text'))
        self.assertIn('обнуление',self.design.restart_button.cget('text'))

    def test_default_window_shows_two_history_rows_and_reset_text_fits(self):
        self.root.geometry('840x890+10000+10000')
        self.app.group_frame.grid()
        for index in range(2):
            self.app.history_table.insert('', 'end', iid=f'event-{index}',
                                          values=('', '12:00:00', '100 000', '3 мин'))
        self.root.update()
        row=self.app.history_table.bbox('event-1','peak')
        self.assertTrue(row)
        self.assertLessEqual(row[1]+row[3],self.app.history_table.winfo_height())
        self.assertLessEqual(sum(self.app.history_table.column(c,'width') for c in ('time','peak','interval')),
                             self.app.history_table.winfo_width())
        button=self.design.restart_button
        self.assertNotIn('\n',button.cget('text'))
        for item in button.find_all():
            if button.type(item)=='text':
                bounds=button.bbox(item)
                self.assertGreaterEqual(bounds[0],5)
                self.assertLessEqual(bounds[2],button.winfo_width()-5)

    def test_empty_history_and_details_safety_actions(self):
        self.design.update_empty_history()
        self.root.update()
        self.assertTrue(self.design.empty_history.winfo_viewable())
        self.assertIn('Обнулений пока нет',[self.design.empty_history.itemcget(i,'text')
                         for i in self.design.empty_history.find_all() if self.design.empty_history.type(i)=='text'])
        self.design.toggle_details()
        self.design.stop_all_button.invoke()
        self.app.emergency_stop.assert_called_once()
        self.app.log_panel.close_button.invoke()
        self.app.toggle_logs.assert_called_once()
        self.assertEqual(self.app.other_program_button.cget('style'),'Top.TButton')

    def test_bottom_history_handle_extends_window_and_history(self):
        before=self.root.winfo_height()
        history=self.app.history_table.winfo_height()
        self.design.begin_history_resize(SimpleNamespace(y_root=400))
        self.design.drag_history_resize(SimpleNamespace(y_root=500))
        self.root.update()
        self.assertEqual(self.root.winfo_height(),before+100)
        self.assertGreater(self.app.history_table.winfo_height(),history)

    def test_percent_mode_raises_divider_and_gives_space_to_history(self):
        self.root.update()
        range_sash=self.design.history_splitter.sashpos(0)
        history_height=self.app.history_table.winfo_height()
        self.app.start_method_var.set('percent')
        self.root.update()
        self.assertLess(self.design.history_splitter.sashpos(0),range_sash)
        self.assertGreater(self.app.history_table.winfo_height(),history_height)
        self.app.start_method_var.set('range')
        self.root.update()
        self.assertEqual(self.design.history_splitter.sashpos(0),range_sash)

    def test_bottom_handle_uses_compact_grip_without_pink_track(self):
        bar=self.design.history_resize_bar
        self.design.draw_history_resize_bar()
        self.assertEqual(int(bar.cget('height')),6)
        self.assertEqual(len(bar.find_all()),10)
        self.assertTrue(all(float(bar.itemcget(item,'width'))==1 for item in bar.find_all()))

    def test_button_redraw_does_not_resolve_combobox_popdown_as_python_widget(self):
        with patch.object(self.design.start_button,'focus_get',side_effect=KeyError('popdown')) as focus:
            self.app.running=True
            self.design.pulse()
            self.assertEqual(self.design.start_button.cget('text'),'Остановить / F8')
            focus.assert_not_called()

    def test_help_and_creator_fit_inside_main_window(self):
        for widget in (self.design.help_button, self.design.creator_name):
            self.assertTrue(widget.winfo_viewable())
            self.assertLessEqual(widget.winfo_rooty()-self.root.winfo_rooty()+widget.winfo_height(),
                                 self.root.winfo_height())
        self.assertEqual(self.design.creator_name.cget('text'), 'casorin')
        self.assertNotEqual(self.design.creator_name.cget('style'), 'Muted.TLabel')

    def test_help_is_reused_and_never_arms_or_starts_monitor(self):
        self.design.open_help()
        self.root.update()
        help_window = self.design.help_window
        self.assertTrue(help_window.winfo_viewable())
        self.design.open_help()
        self.assertIs(self.design.help_window, help_window)
        self.app.toggle.assert_not_called()
        self.app._sync_mode.assert_not_called()
        self.app.apply_range.assert_not_called()
        self.app.reset_lock.assert_not_called()

    def test_help_contains_connection_instructions_and_matches_theme(self):
        from app.help_window import GUIDE
        self.design.open_help()
        self.design.toggle_theme()
        self.root.update()
        self.assertEqual(self.design.help_window.text.cget('background'), '#202b43')
        guide = '\n'.join(text for _title, text in GUIDE)
        for required in ('MEmu', 'LDPlayer', 'BlueStacks', '720 × 1280', '1080 × 1920',
                         'Открыть локальное подключение', 'Android Debug Bridge (ADB)',
                         'F8', 'F9', 'Сохранить настройки'):
            self.assertIn(required, guide)

    def test_click_resolution_recommendation_is_highlighted(self):
        from app.help_window import GUIDE, GuideCard
        from app.ui_design import PALETTES
        text = dict(GUIDE)['Эмуляторы и разрешение']
        paragraph = text.split('\n\n')[1]
        self.assertIn('1080 × 1080', paragraph)
        for theme in ('light', 'dark'):
            card = GuideCard(self.root, paragraph, PALETTES[theme], lambda _event: None)
            self.assertTrue(card.recommendation)
            self.assertTrue(card.callout)
            self.assertIn('bold', card.body.cget('font'))
            card.destroy()

    def test_help_uses_current_buttons_and_connection_steps_in_first_launch(self):
        from app.help_window import GUIDE
        self.assertEqual(GUIDE[0][0],'Первый запуск')
        for text in ('Если нужного окна нет в списке','Открыть локальное подключение',
                     'Android Debug Bridge (ADB)'):
            self.assertIn(text,GUIDE[0][1])
        titles=[title for title,_ in GUIDE]
        self.assertNotIn('Окно не видно в списке',titles)
        self.assertIn('История обнулений',titles)
        self.assertIn('Если программа не работает',titles)
        guide='\n'.join(text for _,text in GUIDE)
        self.assertNotIn('Начать заново',guide)
        self.assertIn('Ждать новое обнуление',guide)
        self.design.open_help()
        self.root.update()
        labels=[]
        def collect(widget):
            if widget.winfo_class() in ('TLabel','Label'):
                labels.append(widget.cget('text'))
            for child in widget.winfo_children():
                collect(child)
        collect(self.design.help_window)
        self.assertNotIn('Помощь ничего не включает и не меняет ваши настройки.',labels)

    def test_help_cards_and_pink_scrollbar_resize_and_switch_topics(self):
        from app.window_picker import PinkScrollbar
        self.design.open_help()
        help_window=self.design.help_window
        self.root.update()
        self.assertIsInstance(help_window.scrollbar,PinkScrollbar)
        self.assertEqual(help_window.cards[0].step.group(1),'1')
        self.assertTrue(any(card.callout for card in help_window.cards))
        self.assertTrue(any(card.body.tag_ranges('button') for card in help_window.cards))
        old_cards=list(help_window.cards)
        help_window.topics.selection_set(5)
        help_window.show_topic()
        self.root.update()
        self.assertTrue(all(not card.winfo_exists() for card in old_cards))
        self.assertIn('История обнулений',help_window.text.get('1.0','end'))
        help_window.geometry('840x600')
        self.root.update()
        self.assertTrue(all(card.winfo_reqwidth()<=help_window.text.winfo_width() for card in help_window.cards))
        self.assertLess(max(card.winfo_reqheight() for card in help_window.cards),400)

    def test_help_blue_palette_is_stronger_without_changing_main_theme(self):
        from app.ui_design import PALETTES
        original=dict(PALETTES['light'])
        self.design.open_help()
        help_window=self.design.help_window
        help_window.apply_palette(PALETTES['light'])
        self.root.update()
        self.assertEqual(help_window.cget('background'),'#d9efff')
        callout=next(card for card in help_window.cards if card.callout)
        self.assertEqual(callout.body.cget('background'),'#d3ecff')
        self.assertEqual(PALETTES['light'],original)

    def tearDown(self):
        for job in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(job)
        self.root.destroy()
        self.directory.cleanup()

    def test_theme_persists_without_touching_game_configuration(self):
        self.design.toggle_theme()
        self.assertEqual(load_theme(self.design.preferences), 'dark')
        self.assertFalse((Path(self.directory.name)/'user_config.json').exists())
        self.design.toggle_theme()
        self.assertEqual(load_theme(self.design.preferences), 'light')

    def test_real_mode_uses_existing_confirmation_callback(self):
        self.design.choose_mode(True)
        self.app._sync_mode.assert_called_once()

    def test_controls_fit_when_details_are_open(self):
        self.design.toggle_details()
        self.root.geometry('1000x900+10000+10000')
        self.root.update()
        for widget in (self.app.clear_history_button,
                       self.design.details_button, self.design.start_button):
            self.assertTrue(widget.winfo_viewable(), str(widget))
            bottom = widget.winfo_rooty()-self.root.winfo_rooty()+widget.winfo_height()
            self.assertLessEqual(bottom, self.root.winfo_height())

    def test_two_window_summary_fits_without_hiding_controls(self):
        sessions = {str(i): SimpleNamespace(window=SimpleNamespace(name=f'MEmu {i}'),
                                           monitor=SimpleNamespace(state=MonitorState())) for i in range(2)}
        self.app._group = SimpleNamespace(sessions=sessions, any_real=False)
        self.app._focus_uuid = '0'
        self.app._session_statuses = {}
        AppWindow._update_group_table(self.app)
        self.root.geometry('1000x900+10000+10000')
        self.root.update()
        for widget in (self.app.group_picker, self.design.start_button, self.design.details_button):
            self.assertTrue(widget.winfo_viewable())
            bottom = widget.winfo_rooty()-self.root.winfo_rooty()+widget.winfo_height()
            self.assertLessEqual(bottom,self.root.winfo_height())

    def test_compact_window_and_resizable_history(self):
        self.root.geometry('840x890+10000+10000')
        self.root.update()
        self.assertLessEqual(self.root.winfo_width()*self.root.winfo_height(), 1100*1120*.61)
        self.assertTrue(self.app.history_table.winfo_viewable())
        self.assertGreater(self.app.history_table.winfo_height(), 45)
        before = self.app.history_table.winfo_height()
        self.root.geometry('900x980+10000+10000')
        self.root.update()
        self.assertGreater(self.app.history_table.winfo_height(), before)
        sash = self.design.history_splitter.sashpos(0)
        self.design.history_splitter.sashpos(0, sash+30)
        self.root.update()
        self.assertEqual(self.design.history_splitter.sashpos(0), sash+30)

    def test_creator_link_opens_only_telegram(self):
        from unittest.mock import patch
        with patch('webbrowser.open') as opened:
            self.design.open_creator()
            opened.assert_called_once_with('https://t.me/casorin')

    def test_coffee_link_has_requested_text_and_opens_boosty(self):
        self.assertEqual(self.design.coffee_link.cget('text'),'на кофе💜')
        self.assertEqual(self.design.coffee_link.cget('style'),'Creator.TLabel')
        self.assertTrue(self.design.coffee_link.winfo_viewable())
        with patch('webbrowser.open') as opened:
            self.design.open_coffee()
            opened.assert_called_once_with('https://boosty.to/casorin/donate')

    def test_dragging_does_not_save_or_apply_range(self):
        self.design.dragging = 0
        self.design.drag_range(SimpleNamespace(x=200))
        self.app.apply_range.assert_not_called()
        self.assertFalse((Path(self.directory.name)/'user_config.json').exists())

    def test_unlimited_checkbox_disables_upper_field(self):
        self.app.no_upper_var.set(True)
        self.design.update_upper_entry()
        self.assertTrue(self.design.upper_entry.instate(['disabled']))
        self.app.no_upper_var.set(False)
        self.design.update_upper_entry()
        self.assertFalse(self.design.upper_entry.instate(['disabled']))

    def test_percentage_selection_hides_inactive_range(self):
        self.app.start_method_var.set('percent')
        self.root.update()
        self.assertFalse(self.design.range_entries.winfo_ismapped())
        self.assertFalse(self.design.slider.winfo_ismapped())
        self.assertFalse(self.design.range_line.winfo_ismapped())
        self.assertFalse(self.design.percent_entry.instate(['disabled']))
        self.assertIn('Сохранить', self.design.settings_note.get())
        self.app.start_method_var.set('range')
        self.root.update()
        self.assertTrue(self.design.range_entries.winfo_ismapped())
        self.assertTrue(self.design.slider.winfo_ismapped())
        self.assertTrue(self.design.percent_entry.instate(['disabled']))

    def test_percent_minimum_preview_and_unsaved_hint(self):
        event=SimpleNamespace(peak_before_reset=100000)
        self.app.monitor=SimpleNamespace(_latest_percentage_reset=lambda:event)
        self.app.start_method_var.set('percent')
        self.app.start_percent_var.set('80')
        self.app.percent_floor_var.set('90 000')
        self.app.percent_floor_enabled_var.set(True)
        self.root.update()
        self.assertEqual(self.design.percent_threshold.get(),'90 000')
        self.assertIn('ещё не применены',self.design.settings_note.get())
        self.assertFalse(self.design.percent_floor_entry.instate(['disabled']))
        self.app.percent_floor_enabled_var.set(False)
        self.root.update()
        self.assertEqual(self.design.percent_threshold.get(),'80 000')
        self.assertTrue(self.design.percent_floor_entry.instate(['disabled']))

    def test_percent_minimum_is_left_of_threshold_and_has_small_card_checkbox(self):
        from tkinter import ttk
        from app.ui_design import PALETTES
        self.app.start_method_var.set('percent')
        self.root.update()
        check=self.design.percent_floor_check
        self.assertLess(check.winfo_rootx(),self.design.percent_threshold_box.winfo_rootx())
        self.assertEqual(check.cget('style'),'SmallWallet.Card.TCheckbutton')
        for theme in ('light','dark'):
            self.design.theme=theme
            self.design.apply_theme()
            style=ttk.Style(self.root)
            self.assertEqual(style.lookup('SmallWallet.Card.TCheckbutton','background'),PALETTES[theme]['card'])
            image=self.design.theme_images[f'Fountain.{theme}.SmallWalletCheck'][0]
            self.assertEqual((image.width(),image.height()),(16,16))

    def test_percent_preview_uses_draft_percent_not_saved_range(self):
        event=SimpleNamespace(peak_before_reset=100000)
        self.app.monitor=SimpleNamespace(_latest_percentage_reset=lambda:event)
        self.app.start_method_var.set('percent')
        self.app.start_percent_var.set('85')
        self.root.update()
        self.assertEqual(self.design.percent_threshold.get(),'85 000')
        self.assertFalse(self.design.range_line.winfo_ismapped())
        self.app.apply_range.assert_not_called()

    def test_wait_for_reset_clears_elapsed_time_immediately(self):
        self.app.reset_since_var.set('17 мин 02 сек')
        self.app._group=SimpleNamespace(reset_cycle=Mock())
        self.app._session_snapshots={'old':object()}
        with patch('app.ui.messagebox.askyesno',return_value=True):
            AppWindow.reset_lock(self.app)
        self.assertEqual(self.app.reset_since_var.get(),'')
        self.assertEqual(self.app._session_snapshots,{})
        self.app._group.reset_cycle.assert_called_once()

    def test_reference_buttons_keep_existing_actions(self):
        self.design.start_button.invoke()
        self.app.toggle.assert_called_once()
        self.design.restart_button.invoke()
        self.app.reset_lock.assert_called_once()
        self.assertTrue(any(self.design.start_button.itemcget(item,'text') == 'F8'
                            for item in self.design.start_button.find_all()
                            if self.design.start_button.type(item) == 'text'))

    def test_latest_badge_is_visible_for_newest_row(self):
        self.app.history_table.insert('', 'end', iid='event-0', values=('1','12:00:00','100000','2 мин'))
        self.root.update()
        self.design.pulse()
        self.root.update()
        self.assertTrue(self.design.latest_badge.winfo_viewable())

    def test_history_grows_with_window_in_both_directions(self):
        before=(self.app.history_table.winfo_width(),self.app.history_table.winfo_height())
        self.root.geometry('1400x1200+10000+10000')
        self.root.update()
        after=(self.app.history_table.winfo_width(),self.app.history_table.winfo_height())
        self.assertGreater(after[0],before[0])
        self.assertGreater(after[1],before[1])

    def test_f8_hint_tracks_start_and_stop(self):
        self.design.pulse()
        self.assertEqual(self.design.start_button.cget('text'),'Начать / F8')
        self.app.running=True
        self.design.pulse()
        self.assertEqual(self.design.start_button.cget('text'),'Остановить / F8')

    def test_wallet_changes_show_unsaved_hint_until_success(self):
        self.app.gem_limit_enabled_var.set(True)
        self.app.gem_floor_var.set('50000')
        self.assertIn('ещё не применены',self.design.settings_note.get())
        self.app.apply_range()
        self.assertIn('ещё не применены',self.design.settings_note.get())
        self.design.mark_saved()
        self.assertIn('Настройки сохранены',self.design.settings_note.get())
