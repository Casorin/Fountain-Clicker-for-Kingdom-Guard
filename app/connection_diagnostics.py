"""Safe, actionable screenshot errors without addresses or user paths."""
import subprocess


def preview_error_message(error):
    text = str(error).lower()
    if any(word in text for word in ('недостаточно памяти', 'hostmemorylow', 'out of memory', '0xc000012d')):
        return 'Не хватает памяти. Закройте лишние эмуляторы и программы, затем попробуйте снова.'
    if isinstance(error, PermissionError) or any(word in text for word in ('access is denied', 'permission denied', 'winerror 5')):
        return 'Нет доступа к файлу или подключению. Полностью распакуйте программу в отдельную папку, например «Документы». Не отключайте антивирус; если ошибка повторяется, отправьте отчёт.'
    if any(word in text for word in ('no space left', 'disk full', 'winerror 112')):
        return 'На диске закончилось место. Освободите место и запустите программу снова.'
    if 'неоднозначные адреса' in text or 'more than one device' in text:
        return 'У эмуляторов совпадают адреса подключения. Оставьте один тип эмулятора, перезапустите его и обновите снимки. Если проблема повторяется, отправьте отчёт.'
    if any(word in text for word in ('video stream closed', 'video disconnected', 'freshframe', 'свежий видеокадр')):
        return 'Потеряна свежая картинка эмулятора. Дождитесь его загрузки и нажмите «Начать». Если не помогло, выберите это окно заново.'
    if isinstance(error, FileNotFoundError) or 'winerror 2' in text or 'не удалось запустить adb' in text:
        return 'Не удалось запустить ADB. Проверьте установку эмулятора и полностью распакуйте архив программы.'
    if 'unauthorized' in text:
        return 'ADB не разрешён: подтвердите разрешение отладки в эмуляторе.'
    if isinstance(error, subprocess.TimeoutExpired) or 'timeout' in text or 'timed out' in text:
        return 'Эмулятор не ответил вовремя. Дождитесь загрузки и обновите снимки.'
    if any(word in text for word in ('offline', 'недоступно', 'refused', 'cannot connect', 'failed to connect', '10061')):
        return 'Нет подключения к эмулятору. Включите локальную отладку ADB, перезапустите эмулятор и обновите снимки.'
    if any(word in text for word in ('screencap', 'png', 'raw', 'изображ', 'скриншот')):
        return 'ADB подключён, но снимок не удалось прочитать. Перезапустите эмулятор и обновите снимки.'
    return 'Не удалось получить снимок: ' + type(error).__name__ + '. Обновите снимки и отправьте отчёт автору.'
