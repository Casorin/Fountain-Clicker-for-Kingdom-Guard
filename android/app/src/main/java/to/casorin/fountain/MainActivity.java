package to.casorin.fountain;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.media.projection.MediaProjectionManager;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.TextPaint;
import android.text.method.LinkMovementMethod;
import android.text.style.ClickableSpan;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.text.SimpleDateFormat;
import java.util.*;

public final class MainActivity extends Activity {
    public static volatile boolean visible;
    private HistoryStore store;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private LinearLayout content, history;
    private HistoryScrollView historyScroll;
    private TextView status, timer, previous, current;
    private Button start;
    private boolean dark;
    private int ink, muted, background, card, blue, pink;
    private String renderedHistory = "";

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved); store = new HistoryStore(this);
        dark = store.preferences.getBoolean("dark", false); build();
    }
    private void build() {
        ink = Color.parseColor(dark ? "#F1F4FF" : "#111C55");
        muted = Color.parseColor(dark ? "#B8C7E6" : "#526DA4");
        background = Color.parseColor(dark ? "#172238" : "#EAF6FE");
        card = Color.parseColor(dark ? "#23334D" : "#FFFFFF");
        blue = Color.parseColor(dark ? "#284965" : "#D1EEFF");
        pink = Color.parseColor("#FF9CBF");
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.setBackgroundColor(background);
        content = column(); content.setPadding(dp(18), dp(18), dp(18), dp(20)); scroll.addView(content);
        setContentView(scroll);
        scroll.setOnApplyWindowInsetsListener((v, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                Insets i = insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout());
                v.setPadding(i.left, i.top, i.right, i.bottom);
            } else v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        LinearLayout heading = row();
        TextView name = text("Фонтан", 30, true, ink); heading.addView(name, new LinearLayout.LayoutParams(0, -2, 1));
        Button theme = button(dark ? "Светлая тема" : "Тёмная тема", false);
        theme.setTextSize(12); theme.setOnClickListener(v -> { dark = !dark; store.preferences.edit().putBoolean("dark", dark).apply(); build(); });
        heading.addView(theme); content.addView(heading);
        addText(content, "История обнулений · "+BuildConfig.VERSION_NAME+" · тестовая версия", 12, false, muted);

        LinearLayout summary = section(blue);
        addText(summary, "После последнего замеченного обнуления", 14, false, muted);
        timer = text("Ждём обнуление", 30, true, ink); summary.addView(timer);
        previous = text("Прошлый фонд: —", 19, true, ink); summary.addView(previous);
        current = text("Последнее чтение фонда: —", 14, false, muted); summary.addView(current);
        status = text("Наблюдение остановлено", 13, false, muted); summary.addView(status);
        content.addView(summary);

        LinearLayout actions = section(card);
        start = button("Начать наблюдение", true); start.setOnClickListener(v -> {
            if (ObserverService.active() != null) stopService(new Intent(this, ObserverService.class)); else begin();
            refresh();
        }); actions.addView(start, full());
        Button calibrate = button("Настроить область фонда", false);
        icon(calibrate, R.drawable.ic_settings);
        calibrate.setOnClickListener(v -> showCalibration()); actions.addView(calibrate, full());
        Button guide = button("Инструкция и разрешения", false);
        icon(guide, R.drawable.ic_info);
        guide.setTypeface(Typeface.create("sans-serif-condensed",Typeface.NORMAL));
        guide.setOnClickListener(v -> guide()); actions.addView(guide, full());
        addText(actions, "Только наблюдение. Приложение не нажимает кнопки и не расходует самоцветы.", 12, false, muted);
        content.addView(actions);

        LinearLayout historyCard = section(card);
        LinearLayout historyHeading = row(); historyHeading.addView(text("История обнулений", 21, true, ink), new LinearLayout.LayoutParams(0, -2, 1));
        Button clear = button("Очистить", false); clear.setTextSize(12);
        clear.setMinWidth(0); clear.setMinimumWidth(0);
        clear.setMinHeight(dp(40)); clear.setMinimumHeight(dp(40));
        clear.setPadding(dp(10),dp(4),dp(10),dp(4));
        clear.setTypeface(Typeface.create("sans-serif-condensed",Typeface.NORMAL));
        GradientDrawable clearShape = round(card,10);
        clearShape.setStroke(dp(1),Color.parseColor(dark ? "#885F79" : "#F4BDD3"));
        clear.setBackground(clearShape);
        clear.setOnClickListener(v -> new AlertDialog.Builder(this).setTitle("Очистить историю?")
            .setMessage("Записи будут удалены только на этом телефоне.")
            .setNegativeButton("Отмена", null).setPositiveButton("Очистить", (d, w) -> { store.clear(); renderedHistory = ""; refresh(); }).show());
        historyHeading.addView(clear); historyCard.addView(historyHeading);
        LinearLayout labels = row(); labels.setPadding(0,0,dp(8),0);
        labels.setBackground(round(Color.parseColor(dark ? "#293B52" : "#F2F7FC"),8));
        cell(labels,"Время",1); cell(labels,"Прошлый фонд",1.2f); cell(labels,"Интервал",1.1f);
        LinearLayout.LayoutParams headerParams = new LinearLayout.LayoutParams(-1,-2); headerParams.topMargin=dp(8);
        historyCard.addView(labels,headerParams);
        historyScroll = new HistoryScrollView(this);
        historyScroll.setVerticalScrollBarEnabled(true);
        historyScroll.setScrollbarFadingEnabled(false);
        historyScroll.setScrollBarSize(dp(5));
        historyScroll.setVerticalScrollbarThumbDrawable(round(pink,4));
        historyScroll.setVerticalScrollbarTrackDrawable(round(Color.parseColor(dark ? "#4E3546" : "#FCE5EF"),4));
        historyScroll.setScrollBarStyle(View.SCROLLBARS_INSIDE_OVERLAY);
        history = column(); history.setPadding(0,0,dp(8),0);
        historyScroll.addView(history); historyCard.addView(historyScroll);
        addText(historyCard, "Первые 5 записей видны сразу. Остальные — прокрутите таблицу.\nЗаписываются только замеченные и подтверждённые обнуления.", 12, false, muted);
        content.addView(historyCard);
        Button report = button("Сообщить об ошибке",false); icon(report,R.drawable.ic_report);
        report.setOnClickListener(v -> reportBug());
        LinearLayout.LayoutParams reportParams = full(); reportParams.topMargin=dp(14);
        content.addView(report,reportParams);
        TextView creator = text("",14,false,muted);
        SpannableString footer = new SpannableString("Created by: casorin   ·   на кофе💜");
        footerLink(footer,"casorin","https://t.me/casorin");
        footerLink(footer,"на кофе💜","https://boosty.to/casorin/donate");
        creator.setText(footer); creator.setMovementMethod(LinkMovementMethod.getInstance());
        creator.setHighlightColor(Color.TRANSPARENT); creator.setGravity(Gravity.CENTER);
        creator.setPadding(0,dp(10),0,dp(10)); creator.setMinHeight(dp(48)); content.addView(creator);
        renderedHistory = ""; refresh();
    }
    private void begin() {
        if (!Settings.canDrawOverlays(this)) {
            new AlertDialog.Builder(this).setTitle("Таймер поверх игры")
                .setMessage("В следующем окне разрешите приложению «Фонтан · История» показываться поверх других приложений. После этого вернитесь сюда и нажмите «Начать наблюдение».")
                .setNegativeButton("Отмена", null).setPositiveButton("Открыть настройку", (d, w) ->
                    startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:"+getPackageName())))).show();
            return;
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
                && !store.preferences.getBoolean("notificationAsked", false)) {
            store.preferences.edit().putBoolean("notificationAsked", true).apply();
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 21); return;
        }
        new AlertDialog.Builder(this).setTitle("Разрешить чтение игры")
            .setMessage("Android попросит разрешить показ экрана. Если есть выбор, выберите только Kingdom Guard, а не весь экран. Звук не записывается, изображения никуда не отправляются.\n\nЗатем откройте в игре фонтан. При первом запуске вернитесь сюда и нажмите «Настроить область фонда».")
            .setNegativeButton("Отмена", null).setPositiveButton("Продолжить", (d, w) -> {
                MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
                startActivityForResult(manager.createScreenCaptureIntent(), 22);
            }).show();
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results); if (code == 21) begin();
    }
    @Override protected void onActivityResult(int code, int result, Intent data) {
        super.onActivityResult(code, result, data);
        if (code == 22 && result == RESULT_OK && data != null) {
            startForegroundService(new Intent(this, ObserverService.class).putExtra("consent", data));
            moveTaskToBack(true);
        }
    }
    private void showCalibration() {
        ObserverService service = ObserverService.active();
        if (service == null) { message("Сначала нажмите «Начать наблюдение» и разрешите чтение экрана."); return; }
        if (store.calibrated()) {
            new AlertDialog.Builder(this).setTitle("Настроить область заново?")
                .setMessage("Наблюдение временно остановится. Откройте фонтан, подождите несколько секунд и вернитесь в приложение.")
                .setNegativeButton("Отмена", null).setPositiveButton("Настроить", (d, w) -> {
                    service.requestCalibration(); moveTaskToBack(true);
                }).show(); return;
        }
        Bitmap screenshot = service.copyCalibrationFrame();
        if (screenshot == null) { message("Откройте фонтан в игре, подождите несколько секунд, затем вернитесь сюда. После этого нажмите эту кнопку ещё раз."); return; }
        RegionView view = new RegionView(screenshot, store.region());
        LinearLayout body = column(); body.setPadding(dp(12), dp(8), dp(12), 0);
        TextView hint = text("Обведите только жёлтые цифры призового фонда: проведите пальцем от верхнего левого до нижнего правого угла цифр. Не захватывайте алмаз и заголовок. Уведомлений поверх цифр быть не должно.", 14, false, Color.rgb(17,28,85));
        body.addView(hint);
        Button zoom = button("Показать весь снимок",false);
        zoom.setTextSize(12); zoom.setOnClickListener(v -> zoom.setText(view.toggleZoom() ? "Показать весь снимок" : "Увеличить область фонда"));
        body.addView(zoom,full()); body.addView(view, new LinearLayout.LayoutParams(-1, dp(300)));
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("Где находится призовой фонд?").setView(body)
            .setNegativeButton("Отмена", null).setPositiveButton("Проверить цифры", null).create();
        FrameRecognizer testReader = new FrameRecognizer();
        double[][] checked = {null};
        Long[] checkedValue = {null};
        dialog.setOnDismissListener(d -> { testReader.close(); screenshot.recycle(); });
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            if (ObserverService.active() != service) { message("Наблюдение остановлено. Запустите его заново."); dialog.dismiss(); return; }
            if (!view.valid()) { hint.setText("Рамка слишком мала или слишком высока. Обведите только цифры фонда."); return; }
            if (checkedValue[0] != null && Arrays.equals(checked[0],view.region)) {
                if (!service.calibrate(view.region,screenshot)) {
                    hint.setText("Цифры прочитаны, но заголовок фонда над ними не найден. Проверьте, что обведён именно призовой фонд."); return;
                }
                dialog.dismiss();
                Toast.makeText(this,"Область сохранена",Toast.LENGTH_SHORT).show();
                moveTaskToBack(true);
                return;
            }
            double[] tested = view.region.clone();
            Button confirm = dialog.getButton(AlertDialog.BUTTON_POSITIVE); confirm.setEnabled(false); confirm.setText("Проверяю…");
            testReader.readDetailed(screenshot,tested,result -> {
                if (!dialog.isShowing()) return;
                confirm.setEnabled(true);
                if (result.value() == null) {
                    checkedValue[0] = null; confirm.setText("Проверить ещё раз");
                    hint.setText(getString(R.string.calibration_failed,result.detail())); return;
                }
                checked[0] = tested; checkedValue[0] = result.value();
                hint.setText(getString(R.string.calibration_read,HistoryStore.amount(result.value())));
                confirm.setText("Сохранить");
            });
        })); dialog.show();
    }
    private final class RegionView extends View {
        private final Bitmap image;
        final double[] region;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF fit = new RectF();
        private final RectF selection = new RectF();
        private float beginX, beginY;
        private boolean zoomed = true;
        private float focusX, focusY;
        RegionView(Bitmap image, double[] initial) {
            super(MainActivity.this); this.image = image; region = initial.clone();
            focusX = (float)(region[0]+region[2])/2; focusY = (float)(region[1]+region[3])/2;
        }
        boolean toggleZoom() {
            zoomed = !zoomed;
            if (zoomed) { focusX = (float)(region[0]+region[2])/2; focusY = (float)(region[1]+region[3])/2; }
            invalidate(); return zoomed;
        }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas); canvas.drawColor(Color.rgb(213,239,255));
            float scale = zoomed ? Math.min(getWidth()/(image.getWidth()*.6f),getHeight()/(image.getHeight()*.3f))
                : Math.min((float)getWidth()/image.getWidth(), (float)getHeight()/image.getHeight());
            float w = image.getWidth()*scale, h = image.getHeight()*scale;
            float left = zoomed ? getWidth()/2f-w*focusX : (getWidth()-w)/2;
            float top = zoomed ? getHeight()/2f-h*focusY : (getHeight()-h)/2;
            fit.set(left,top,left+w,top+h);
            paint.setStyle(Paint.Style.FILL); paint.setAlpha(255); canvas.drawBitmap(image, null, fit, paint);
            selection.set(fit.left+(float)region[0]*w, fit.top+(float)region[1]*h, fit.left+(float)region[2]*w, fit.top+(float)region[3]*h);
            paint.setColor(Color.argb(50,255,80,150)); canvas.drawRect(selection, paint);
            paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(dp(2)); paint.setColor(Color.rgb(255,90,155)); canvas.drawRect(selection, paint);
            paint.setStyle(Paint.Style.FILL);
        }
        @Override public boolean onTouchEvent(android.view.MotionEvent e) {
            if (fit.width() <= 0) return false;
            float x = Math.max(0, Math.min(1, (e.getX()-fit.left)/fit.width()));
            float y = Math.max(0, Math.min(1, (e.getY()-fit.top)/fit.height()));
            if (e.getAction() == MotionEvent.ACTION_DOWN) { beginX = x; beginY = y; getParent().requestDisallowInterceptTouchEvent(true); }
            if (e.getAction() == MotionEvent.ACTION_MOVE || e.getAction() == MotionEvent.ACTION_UP) {
                region[0] = Math.min(beginX,x); region[1] = Math.min(beginY,y); region[2] = Math.max(beginX,x); region[3] = Math.max(beginY,y); invalidate();
            }
            if (e.getAction() == MotionEvent.ACTION_UP) performClick(); return true;
        }
        @Override public boolean performClick() { super.performClick(); return true; }
        boolean valid() { return region[2]-region[0] >= .03 && region[3]-region[1] >= .008 && region[3]-region[1] <= .08; }
    }
    private void refresh() {
        if (status == null) return;
        ObserverService service = ObserverService.active();
        status.setText(service == null ? "Наблюдение остановлено" : service.status+(service.accelerated() ? " · ускоренная проверка" : ""));
        start.setText(service == null ? "Начать наблюдение" : "Остановить наблюдение");
        current.setText(getString(R.string.current_fund, service == null || service.current == 0 ? "—" : HistoryStore.amount(service.current)));
        JSONArray events = store.events(); JSONObject last = events.optJSONObject(0);
        timer.setText(last == null ? "Ждём обнуление" : HistoryStore.duration(System.currentTimeMillis()-last.optLong("time")));
        previous.setText(getString(R.string.previous_fund, last == null ? "—" : HistoryStore.amount(last.optLong("fund"))));
        String serialized = events.toString();
        if (!serialized.equals(renderedHistory)) { renderedHistory = serialized; renderHistory(events); }
    }
    private void renderHistory(JSONArray events) {
        history.removeAllViews();
        if (events.length() == 0) { addText(history, "Обнулений пока нет\nЗдесь появятся время и фонд перед падением.", 14, false, muted); return; }
        SimpleDateFormat time = new SimpleDateFormat("dd.MM HH:mm:ss", Locale.getDefault());
        for (int i = 0; i < events.length(); i++) {
            JSONObject event = events.optJSONObject(i); if (event == null) continue;
            LinearLayout r = row(); r.setMinimumHeight(dp(56));
            if (i == 0) r.setBackground(round(Color.parseColor(dark ? "#493549" : "#FFF0F6"),8));
            else if (i % 2 == 0) r.setBackground(round(Color.parseColor(dark ? "#28394E" : "#F8FAFD"),8));
            cell(r, time.format(new Date(event.optLong("time")))+(i == 0 ? "\nПоследнее" : ""), 1);
            cell(r, HistoryStore.amount(event.optLong("fund")), 1.2f);
            cell(r, event.has("interval") && !event.isNull("interval") ? HistoryStore.duration(event.optLong("interval")) : "Неизвестно", 1.1f);
            history.addView(r);
        }
        historyScroll.scrollTo(0,0);
    }

    private void reportBug() {
        String report = DiagnosticReport.create(this,store);
        ClipboardManager clipboard = getSystemService(ClipboardManager.class);
        ClipData data = ClipData.newPlainText("Фонтан — диагностика",report);
        if (Build.VERSION.SDK_INT >= 33) {
            PersistableBundle extras = new PersistableBundle();
            extras.putBoolean(android.content.ClipDescription.EXTRA_IS_SENSITIVE,true);
            data.getDescription().setExtras(extras);
        }
        try {
            clipboard.setPrimaryClip(data);
            Toast.makeText(this,"Отчёт скопирован. Открываю форму с отчётом",Toast.LENGTH_LONG).show();
        } catch (RuntimeException ignored) {
            Toast.makeText(this,"Не удалось скопировать. Отчёт будет заполнен в форме",Toast.LENGTH_LONG).show();
        }
        open(SupportForm.prefilledUrl(report));
    }

    private void footerLink(SpannableString text, String label, String url) {
        int begin = text.toString().indexOf(label);
        text.setSpan(new ClickableSpan() {
            @Override public void onClick(View view) { open(url); }
            @Override public void updateDrawState(TextPaint paint) {
                paint.setColor(Color.parseColor("#FFA8CA")); paint.setUnderlineText(false);
            }
        },begin,begin+label.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
    }

    private void icon(Button button, int resource) {
        button.setCompoundDrawablesWithIntrinsicBounds(resource,0,0,0);
        button.setCompoundDrawablePadding(dp(8));
    }
    private void guide() {
        String instructions = "1. Откройте Kingdom Guard и перейдите в фонтан.\n\n"
            +"2. Здесь нажмите «Начать наблюдение». Разрешите показ поверх других приложений и чтение экрана. На Android 14 и новее выбирайте только игру, если Android предлагает такой выбор.\n\n"
            +"3. При первом запуске откройте фонтан, подождите несколько секунд, затем вернитесь сюда и нажмите «Настроить область фонда». Обведите только жёлтые цифры фонда.\n\n"
            +"4. При настройке нажмите «Проверить цифры». Убедитесь, что показанная сумма совпала с фондом, и нажмите «Сохранить».\n\n"
            +"5. Вернитесь в игру. Маленькую панель можно двигать за любую её часть. Короткое нажатие раскрывает кнопки: − и + меняют размер, ≡ открывает историю, × закрывает панель. Размер также меняется двумя пальцами или за розовый уголок справа снизу. При перетаскивании появляется крестик внизу: отпустите панель над ним, чтобы закрыть её. «Стоп» и крестик останавливают наблюдение, но не удаляют историю.\n\n"
            +"История появится после первого замеченного и подтверждённого обнуления. Сразу видны первые 5 записей, остальные можно посмотреть прокруткой внутри таблицы. Прошлый фонд — последнее подтверждённое значение перед падением. Время — момент, когда приложение заметило падение, а не гарантированно точное время события на сервере.\n\n"
            +"После скрытия игры, блокировки телефона или долгого перекрытия цифр часть обнулений может быть пропущена. Приложение не может узнать их задним числом. Таймер показывает время с последней сохранённой записи, а не обещает время следующего выигрыша.\n\n"
            +"Если размер или ориентация экрана изменились, настройте область заново. Если цифры закрыты уведомлением, дождитесь его исчезновения.\n\n"
            +"После признака уведомления о награде или подтверждённого расхода самоцветов на желания программа проверяет фонд чаще: целевой интервал уменьшается с 300 до 150 мс. После подтверждённого обнуления возвращается обычная частота. Если телефон не успевает распознавать так быстро, новая проверка ждёт завершения предыдущей. Закрытые цифры не угадываются. Расход проверяется для текущей стоимости желания: 100 самоцветов. Не закрывайте плавающей панелью верхний баланс самоцветов. Баланс используется только на телефоне и не попадает в отчёт.\n\n"
            +"Разрешения нужны только для панели и чтения картинки. Специальные возможности, доступ к контактам и микрофону не нужны. Скриншоты не отправляются в интернет. История хранится на телефоне.\n\n"
            +"Если возникла проблема, нажмите «Сообщить об ошибке». Технический отчёт скопируется и откроется в Google Форме. Опишите проблему, при желании добавьте снимок экрана и контакт для ответа. Для загрузки снимка Google попросит войти в аккаунт. Форма сама не отправляется — проверьте её и нажмите кнопку отправки.\n\n"
            +"Это тестовая версия для Android 10 и новее. Совместимость с конкретными телефонами ещё проверяется.";
        TextView body = text(instructions, 16, false, ink); body.setPadding(dp(18),dp(16),dp(18),dp(16));
        body.setBackgroundColor(blue); ScrollView scroll = new ScrollView(this); scroll.addView(body);
        new AlertDialog.Builder(this).setTitle("Всё просто. Давайте разберёмся.").setView(scroll).setPositiveButton("Понятно", null).show();
    }
    private void message(String value) { new AlertDialog.Builder(this).setMessage(value).setPositiveButton("Понятно", null).show(); }
    private void open(String url) { try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); } catch (ActivityNotFoundException ignored) { message("Не найден браузер для открытия ссылки."); } }
    private LinearLayout column() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.VERTICAL); return v; }
    private LinearLayout row() { LinearLayout v = new LinearLayout(this); v.setGravity(Gravity.CENTER_VERTICAL); return v; }
    private LinearLayout section(int color) { LinearLayout v = column(); v.setPadding(dp(16),dp(16),dp(16),dp(16)); v.setBackground(round(color,20)); LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1,-2); p.topMargin = dp(14); v.setLayoutParams(p); return v; }
    private GradientDrawable round(int color, int radius) { GradientDrawable d = new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(radius)); return d; }
    private TextView text(String value, int size, boolean bold, int color) { TextView t = new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(color); t.setTypeface(Typeface.create("sans-serif-condensed",bold ? Typeface.BOLD : Typeface.NORMAL)); t.setPadding(0,dp(3),0,dp(3)); return t; }
    private void addText(LinearLayout parent, String value, int size, boolean bold, int color) { parent.addView(text(value,size,bold,color)); }
    private Button button(String value, boolean primary) { Button b = new Button(this); b.setText(value); b.setAllCaps(false); b.setTextColor(primary ? Color.rgb(17,28,85) : ink); b.setTextSize(15); b.setTypeface(Typeface.create("sans-serif-condensed",Typeface.BOLD)); b.setMinHeight(dp(48)); b.setMinimumHeight(dp(48)); b.setStateListAnimator(null); b.setElevation(0); GradientDrawable d = round(primary ? pink : card,12); if (!primary) d.setStroke(dp(1),Color.parseColor(dark ? "#526680" : "#C3DDF1")); b.setBackground(d); b.setPadding(dp(12),dp(8),dp(12),dp(8)); return b; }
    private LinearLayout.LayoutParams full() { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1,-2); p.bottomMargin = dp(8); return p; }
    private void cell(LinearLayout row, String value, float weight) { TextView t = text(value,12,false,ink); t.setGravity(Gravity.CENTER); t.setPadding(dp(2),dp(10),dp(2),dp(10)); row.addView(t,new LinearLayout.LayoutParams(0,-2,weight)); }
    private int dp(int value) { return (int)(value*getResources().getDisplayMetrics().density+.5f); }
    private final Runnable tick = new Runnable() { @Override public void run() { refresh(); ui.postDelayed(this,1000); } };
    @Override protected void onResume() { super.onResume(); visible = true; ui.removeCallbacks(tick); tick.run(); }
    @Override protected void onPause() { visible = false; ui.removeCallbacks(tick); super.onPause(); }
    @Override protected void onDestroy() { ui.removeCallbacks(tick); super.onDestroy(); }
}
