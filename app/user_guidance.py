"""Plain-language explanations; these helpers never change click permissions."""


def action_block_reason(app):
    if getattr(app, '_window_close_started', False):
        return 'Программа закрывается. Дождитесь закрытия и откройте её снова.'
    if getattr(app, '_switching_window', False):
        return 'Подключаем выбранные окна. Подождите завершения подключения и попробуйте снова.'
    if getattr(app, '_window_picker_active', False):
        return 'Сначала завершите выбор: отметьте нужные окна и нажмите «Выбрать окна» или «Отмена».'
    if 'уже используется' in (getattr(app, '_selection_error', None) or ''):
        return 'Этот аккаунт уже выбран в другом окне кликера. Закройте то окно программы или выберите здесь другой аккаунт. Эмулятор закрывать не нужно.'
    if getattr(app, '_selection_error', None) or (hasattr(app, '_selected_windows') and not app._selected_windows):
        return 'Сначала нажмите «Выбрать окно эмулятора», дождитесь снимка, отметьте нужное окно и подтвердите выбор. Если снимка нет, следуйте подсказке справа.'
    return ''


def observation_help(app):
    blocked = action_block_reason(app)
    if blocked:
        return blocked
    if getattr(app, 'ocr_warmup_error', None):
        return 'Подготовка не завершилась. Нажмите «Повторить». Если ошибка повторится, отправьте отчёт через «Сообщить об ошибке».'
    if not getattr(app, 'ocr_warmup_complete', True):
        return 'Готовим распознавание. Подождите: после подготовки запрошенный запуск начнётся автоматически.'
    errors = getattr(app, '_session_statuses', {})
    focus = getattr(app, '_focus_uuid', None)
    if errors.get(focus, '').startswith('Ошибка подключения:'):
        return errors[focus]
    last_status = getattr(getattr(getattr(app, 'monitor', None), 'state', None), 'last_status', '')
    if 'достигнут сохранённый остаток' in last_status:
        return 'Достигнут сохранённый запас самоцветов. Кликов больше нет. Измените запас и сохраните настройки, только если хотите потратить больше.'
    if not getattr(app, 'running', False):
        return 'Наблюдение остановлено. Нажмите «Начать» или F8. F9 выключает настоящие клики во всех окнах.'
    snapshot = getattr(app, '_session_snapshots', {}).get(focus) or getattr(app, '_poll_result', None)
    if snapshot is None:
        return 'Получаем первый снимок. Если ожидание затянулось, проверьте загрузку эмулятора и локальную отладку ADB.'
    if not snapshot.event_screen_ok or not snapshot.button_visible:
        return 'Откройте фонтан в этом аккаунте: должны быть видны призовой фонд и кнопка «Загадать желание». Закройте игровые меню и всплывающие окна.'
    if snapshot.phase.value == 'RESET_COOLDOWN':
        return f'После обнуления действует двухминутная пауза. Осталось: {snapshot.cooldown_remaining or 0} сек. Ничего нажимать не нужно.'
    if getattr(app.monitor.state, 'start_requires_new_reset', False):
        return 'С последнего обнуления прошло больше 15 минут или его время неизвестно. Ждём новое подтверждённое обнуление.'
    if snapshot.phase.value in {'RESET_TIME_UNKNOWN', 'LOCKED'}:
        return 'Ждём подтверждённое обнуление или завершение начального наблюдения. Кликов пока нет; следите за таймером и статусом.'
    if snapshot.phase.value in {'PAUSED', 'EMERGENCY_STOP'}:
        return 'Это окно остановлено. Проверьте сообщение в «Сведениях о работе», затем нажмите F8 для запуска. Настоящие клики после F9 нужно включить заново.'
    if getattr(snapshot.ocr_status, 'value', '') != 'Число видно':
        return 'Проверяем цифры фонда. Если их закрывает награда, дождитесь исчезновения уведомления. Для кликов рекомендуем 1080 × 1080.'
    if not app.mode_var.get():
        return 'Включён режим «Без кликов»: программа только наблюдает. Для автоматических желаний выберите «С кликами».'
    monitor = app.monitor
    floor = getattr(monitor.user_range, 'minimum_gems', None)
    wallet = getattr(monitor, 'gem_guard', None)
    if floor is not None and wallet is not None:
        balance = getattr(wallet, 'balance', None)
        if balance is None:
            return 'Проверяем запас самоцветов. Убедитесь, что баланс виден на экране. До подтверждения баланса кликов не будет.'
        if balance - 100 < floor:
            return 'Клики остановлены, чтобы сохранить указанный запас самоцветов. Измените запас и сохраните настройки, только если хотите потратить больше.'
    if snapshot.phase.value == 'ACTIVE_CLICKING':
        return 'Клики разрешены. Скорость может быть ниже заданной, пока проверяем свежую картинку и защитные условия.'
    return f'Ждём выполнения сохранённого правила: {monitor.target_range_label()}. Если вы изменили цифры, нажмите «Сохранить настройки».'
