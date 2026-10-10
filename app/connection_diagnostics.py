"""Safe, actionable screenshot errors without addresses or user paths."""
import subprocess


def preview_error_message(error):
    text = str(error).lower()
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
