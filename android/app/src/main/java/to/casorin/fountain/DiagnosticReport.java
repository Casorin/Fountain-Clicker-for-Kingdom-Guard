package to.casorin.fountain;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.DisplayMetrics;
import java.time.Instant;
import java.util.Locale;

public final class DiagnosticReport {
    private DiagnosticReport() {}

    public static String create(Context context, HistoryStore store) {
        DisplayMetrics screen = context.getResources().getDisplayMetrics();
        ObserverService service = ObserverService.active();
        StringBuilder report = new StringBuilder("Фонтан · История — диагностика Android\n");
        report.append("Версия: ").append(BuildConfig.VERSION_NAME).append(" (").append(BuildConfig.VERSION_CODE).append(")\n")
            .append("Время UTC: ").append(Instant.now()).append('\n')
            .append("Устройство: ").append(Build.MANUFACTURER).append(' ').append(Build.MODEL).append('\n')
            .append("Android: ").append(Build.VERSION.RELEASE).append("; API: ").append(Build.VERSION.SDK_INT).append('\n')
            .append("Экран приложения: ").append(screen.widthPixels).append(" × ").append(screen.heightPixels).append('\n')
            .append("Плотность: ").append(screen.densityDpi).append(" dpi; масштаб шрифта: ")
            .append(context.getResources().getConfiguration().fontScale).append('\n')
            .append("Тема: ").append(store.preferences.getBoolean("dark", false) ? "тёмная" : "светлая").append('\n')
            .append("Показ поверх игры разрешён: ").append(Settings.canDrawOverlays(context)).append('\n')
            .append("Уведомления разрешены: ").append(Build.VERSION.SDK_INT < 33
                || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED).append('\n')
            .append("Без ограничения батареи: ").append(context.getSystemService(PowerManager.class)
                .isIgnoringBatteryOptimizations(context.getPackageName())).append('\n')
            .append("Область настроена: ").append(store.calibrated()).append('\n')
            .append("Область чтения (доли экрана): ");
        for (double coordinate : store.region()) report.append(String.format(Locale.US, "%.4f ", coordinate));
        report.append("\nСоотношение сторон при настройке: ").append(store.preferences.getFloat("aspect", 0))
            .append("\nЗаписей истории: ").append(store.events().length())
            .append("\nOCR: ML Kit Latin 16.0.1; обычный / быстрый интервал: 300 / 150 мс; признаки желаний: 900 мс\n")
            .append("Наблюдение: ").append(service == null ? "остановлено" : "включено").append('\n');
        if (service != null) report.append(service.diagnosticSnapshot());
        else {
            String previous = store.preferences.getString("lastDiagnostic", "");
            if (!previous.isEmpty()) report.append("Последняя сессия (не текущие показания):\n").append(previous);
            else report.append("Данные сессии пока отсутствуют.\n");
        }
        report.append("Баланс, значения фонда, история аккаунта, снимки экрана, сырые тексты OCR, идентификаторы устройства и личные данные не включены.");
        return report.toString();
    }
}
