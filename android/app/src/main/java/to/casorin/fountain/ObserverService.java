package to.casorin.fountain;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.graphics.*;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.*;
import android.os.*;
import android.provider.Settings;
import android.view.*;
import android.widget.*;
import java.nio.ByteBuffer;
import java.lang.ref.WeakReference;
import java.util.concurrent.atomic.AtomicBoolean;

public final class ObserverService extends Service {
    private static volatile WeakReference<ObserverService> instance = new WeakReference<>(null);
    public static ObserverService active() { return instance.get(); }
    public boolean accelerated() { return polling.fast(); }
    private Bitmap calibrationFrame;
    public volatile String status = "Подготовка наблюдения";
    public volatile boolean captureVisible = true;
    public volatile long current;
    private HistoryStore store;
    private final ResetTracker tracker = new ResetTracker();
    private final AdaptivePolling polling = new AdaptivePolling();
    private final Handler main = new Handler(Looper.getMainLooper());
    private HandlerThread worker;
    private Handler frames;
    private MediaProjection projection;
    private VirtualDisplay display;
    private ImageReader images;
    private FrameRecognizer recognizer;
    private WindowManager manager;
    private FloatingPanel panel;
    private TextView closeTarget;
    private int dragX, dragY;
    private WindowManager.LayoutParams panelParams;
    private final AtomicBoolean processing = new AtomicBoolean();
    private long lastSample;
    private volatile long lastFountainAt, lastSignalCheck;
    private volatile boolean ending;
    private volatile int generation;
    private volatile boolean panelMoving;
    private volatile boolean panelOverFund;
    private volatile long pauseUntil;
    private volatile int frameWidth, frameHeight;
    private volatile int attemptedReads, acceptedReads, hiddenReads, failedReads, frameErrors;
    private volatile long lastAcceptedAt, lastReadDuration;
    private long lastDiagnostic;

    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || "stop".equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        if (projection != null) return START_NOT_STICKY;
        Intent consent = intent.getParcelableExtra("consent");
        if (consent == null) { stopSelf(); return START_NOT_STICKY; }
        store = new HistoryStore(this);
        instance = new WeakReference<>(this);
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("observer", "Наблюдение фонтана", NotificationManager.IMPORTANCE_LOW));
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, ObserverService.class).setAction("stop"), PendingIntent.FLAG_IMMUTABLE);
        PendingIntent open = PendingIntent.getActivity(this, 2, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(this, "observer")
            .setSmallIcon(android.R.drawable.ic_menu_recent_history).setContentTitle("Фонтан · История")
            .setContentText("Чтение экрана. Нажатия не выполняются.").setOngoing(true)
            .setContentIntent(open).addAction(new Notification.Action.Builder(null, "Остановить", stop).build()).build();
        startForeground(17, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
        worker = new HandlerThread("fountain-frames"); worker.start(); frames = new Handler(worker.getLooper());
        recognizer = new FrameRecognizer();
        try {
            projection = getSystemService(MediaProjectionManager.class).getMediaProjection(Activity.RESULT_OK, consent);
            projection.registerCallback(new MediaProjection.Callback() {
                @Override public void onStop() { stopSelf(); }
                @Override public void onCapturedContentResize(int width, int height) { if (!ending) resize(width, height); }
                @Override public void onCapturedContentVisibilityChanged(boolean visible) {
                    captureVisible = visible;
                    if (!visible) { tracker.restartSession(); polling.restartSession(); lastFountainAt=0; current = 0; status = "Игра скрыта · наблюдение приостановлено"; }
                }
            }, main);
            android.util.DisplayMetrics metrics = new android.util.DisplayMetrics();
            getSystemService(WindowManager.class).getDefaultDisplay().getRealMetrics(metrics);
            resize(metrics.widthPixels, metrics.heightPixels);
            if (Settings.canDrawOverlays(this)) createPanel();
            tick.run();
            status = store.calibrated() ? "Откройте фонтан в игре" : "Откройте фонтан, затем настройте область фонда";
        } catch (RuntimeException error) {
            status = "Не удалось начать чтение экрана. Запустите наблюдение заново.";
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    private void resize(int width, int height) {
        if (width < 1 || height < 1 || (frameWidth == width && frameHeight == height)) return;
        generation++;
        polling.restartSession(); lastFountainAt=0; lastSignalCheck=0;
        tracker.restartSession(); current = 0;
        ImageReader old = images;
        images = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2);
        images.setOnImageAvailableListener(this::receiveFrame, frames);
        int density = getResources().getDisplayMetrics().densityDpi;
        if (display == null) display = projection.createVirtualDisplay("FountainHistory", width, height, density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, images.getSurface(), null, frames);
        else { display.resize(width, height, density); display.setSurface(images.getSurface()); }
        frameWidth = width; frameHeight = height;
        if (old != null) old.close();
    }

    private void receiveFrame(ImageReader source) {
        Image image;
        try { image = source.acquireLatestImage(); } catch (IllegalStateException ignored) { return; }
        if (image == null) return;
        long now = SystemClock.elapsedRealtime();
        if (!captureVisible || MainActivity.visible) { polling.restartSession(); lastFountainAt=0; }
        if (ending || !captureVisible || MainActivity.visible || panelMoving || now < pauseUntil
                || now-lastSample < polling.intervalMs() || processing.get()) { image.close(); return; }
        if (store.calibrated() && panelOverFund) {
            lastSample = now;
            image.close(); current = 0; status = "Панель закрывает фонд · передвиньте её";
            main.post(() -> tracker.observe(null,now,System.currentTimeMillis())); return;
        }
        lastSample = now;
        Bitmap frame;
        try {
            Image.Plane plane = image.getPlanes()[0];
            ByteBuffer buffer = plane.getBuffer();
            int pixelStride = plane.getPixelStride(), rowStride = plane.getRowStride();
            Bitmap padded = Bitmap.createBitmap(rowStride/pixelStride, image.getHeight(), Bitmap.Config.ARGB_8888);
            padded.copyPixelsFromBuffer(buffer);
            frame = Bitmap.createBitmap(padded, 0, 0, image.getWidth(), image.getHeight());
            if (frame != padded) padded.recycle();
        } catch (RuntimeException ignored) { frameErrors++; image.close(); return; }
        image.close();
        if (ending) { frame.recycle(); return; }
        if (!store.calibrated()) {
            synchronized (this) {
                Bitmap old = calibrationFrame; calibrationFrame = frame;
                if (old != null) old.recycle();
            }
            status = "Фонтан открыт? Вернитесь в приложение и настройте область фонда";
            return;
        }
        if (!matchesCalibrationShape(frame)) { polling.restartSession(); lastFountainAt=0; frame.recycle(); current = 0; status = "Размер экрана изменился · настройте область заново"; return; }
        boolean fountainVisible=FountainGuard.matches(frame,store.region(),store.preferences.getString("anchor",""));
        if(fountainVisible) lastFountainAt=now;
        boolean recentFountain=lastFountainAt>0 && (now-lastFountainAt<=15000 || polling.fast());
        processing.set(true);
        int capturedGeneration = generation;
        if(recentFountain) {
            Bitmap small=Bitmap.createScaledBitmap(frame,200,Math.max(1,frame.getHeight()*200/frame.getWidth()),false);
            int[] pixels=new int[small.getWidth()*small.getHeight()];
            small.getPixels(pixels,0,small.getWidth(),0,0,small.getWidth(),small.getHeight());
            polling.reward(WishPixels.reward(pixels,small.getWidth(),small.getHeight(),store.region()),now);
            // Once accelerated, leave OCR capacity for the fund instead of rechecking spending.
            boolean checkBalance=!polling.fast() && now-lastSignalCheck>=AdaptivePolling.SIGNAL_MS;
            double[] balanceRegion=checkBalance
                ? WishPixels.balanceRegion(pixels,small.getWidth(),small.getHeight(),store.region()) : null;
            if(small!=frame) small.recycle();
            if(checkBalance) {
                lastSignalCheck=now;
                recognizer.readBalance(frame,balanceRegion,value -> main.post(() -> {
                    if(!validFrame(now,capturedGeneration)) { frame.recycle();processing.set(false);return; }
                    polling.balance(value,SystemClock.elapsedRealtime());
                    readFund(frame,now,capturedGeneration,fountainVisible);
                }));
                return;
            }
        }
        readFund(frame,now,capturedGeneration,fountainVisible);
    }

    private boolean validFrame(long now,int capturedGeneration) {
        return !ending && capturedGeneration==generation && captureVisible && !MainActivity.visible && !panelMoving
            && !panelOverFund && SystemClock.elapsedRealtime()>=pauseUntil && SystemClock.elapsedRealtime()-now<=1500;
    }

    private void readFund(Bitmap frame,long now,int capturedGeneration,boolean fountainVisible) {
        if(!validFrame(now,capturedGeneration)) { frame.recycle();processing.set(false);return; }
        if(!fountainVisible) {
            frame.recycle(); current=0; status="Фонтан не виден или закрыт уведомлением";
            hiddenReads++; diagnostic(now); processing.set(false);
            main.post(() -> { if(validFrame(now,capturedGeneration)) tracker.observe(null,now,System.currentTimeMillis()); });
            return;
        }
        attemptedReads++;
        recognizer.readDetailed(frame, store.region(), result -> {
            main.post(() -> {
                try {
                    if (ending || capturedGeneration != generation || !captureVisible || MainActivity.visible || panelMoving || panelOverFund
                        || SystemClock.elapsedRealtime() < pauseUntil || SystemClock.elapsedRealtime()-now > 1500) return;
                    Long value = result.value();
                    ResetTracker.Event event = tracker.observe(value, now, System.currentTimeMillis());
                    current = value == null ? 0 : tracker.current;
                    status = value == null ? result.detail() : "Фонд читается · наблюдение включено";
                    lastReadDuration = SystemClock.elapsedRealtime()-now;
                    if (value != null) { acceptedReads++; lastAcceptedAt = SystemClock.elapsedRealtime(); }
                    else failedReads++;
                    diagnostic(SystemClock.elapsedRealtime());
                    if (event != null) { store.append(event); polling.confirmedReset(); }
                } finally { frame.recycle(); processing.set(false); }
            });
        });
    }

    private boolean matchesCalibrationShape(Bitmap frame) {
        float ratio = store.preferences.getFloat("aspect", 0);
        return ratio > 0 && Math.abs((float)frame.getWidth()/frame.getHeight()-ratio) < .02;
    }
    private void diagnostic(long now) {
        if (BuildConfig.DEBUG && now-lastDiagnostic >= 1000) {
            lastDiagnostic = now;
            android.util.Log.d("FountainOCR","attempts="+attemptedReads+" accepted="+acceptedReads
                +" hidden="+hiddenReads+" status="+status);
        }
    }

    public String diagnosticSnapshot() {
        return "Снимок состояния UTC: "+java.time.Instant.now()+"\n"
            +"Состояние: "+status+"\nКадр: "+frameWidth+" × "+frameHeight
            +"\nИгра видна: "+captureVisible+"; панель перекрывает фонд: "+panelOverFund
            +"\nOCR занят: "+processing.get()+"; поток чтения работает: "+(worker != null && worker.isAlive())
            +"\nПопыток OCR: "+attemptedReads+"; успешных: "+acceptedReads+"; без результата: "+failedReads
            +"\nПроверок с закрытым фонтаном: "+hiddenReads+"; ошибок получения кадра: "+frameErrors
            +"\nПоследнее распознавание, мс: "+lastReadDuration
            +"\nИнтервал проверки фонда, мс: "+polling.intervalMs()+"; ускорение: "+polling.fast()
            +"\nПричина ускорения: "+polling.reason()+"; награды / расходы: "+polling.rewardTriggers()+" / "+polling.balanceTriggers()
            +"\nС последнего успешного чтения, мс: "+(lastAcceptedAt == 0 ? "нет данных" : SystemClock.elapsedRealtime()-lastAcceptedAt)
            +"\n";
    }

    public synchronized Bitmap copyCalibrationFrame() {
        return calibrationFrame == null || calibrationFrame.isRecycled() ? null : calibrationFrame.copy(Bitmap.Config.ARGB_8888, false);
    }
    public void requestCalibration() {
        polling.restartSession(); lastFountainAt=0;
        store.preferences.edit().putBoolean("calibrated", false).apply();
        generation++; tracker.restartSession(); current = 0;
        synchronized (this) { if (calibrationFrame != null) calibrationFrame.recycle(); calibrationFrame = null; }
        status = "Откройте фонтан, затем вернитесь и настройте область";
    }
    public boolean calibrate(double[] region, Bitmap screenshot) {
        byte[] signature = FountainGuard.signature(screenshot, region);
        if (!FountainGuard.usable(signature)) return false;
        store.region(region[0], region[1], region[2], region[3]);
        polling.restartSession(); lastFountainAt=0; lastSignalCheck=0;
        store.preferences.edit().putFloat("aspect", (float)screenshot.getWidth()/screenshot.getHeight())
            .putString("anchor", FountainGuard.encode(signature)).apply();
        generation++; tracker.restartSession(); current = 0;
        status = "Область сохранена · вернитесь в фонтан";
        updatePanelLayout();
        synchronized (this) { if (calibrationFrame != null) calibrationFrame.recycle(); calibrationFrame = null; }
        return true;
    }

    private void createPanel() {
        manager = getSystemService(WindowManager.class);
        panel = new FloatingPanel(this,store.preferences.getFloat("panelScale",1),store.preferences.getBoolean("dark",false),
            new FloatingPanel.Listener() {
                @Override public void dragStarted() { panelMoving = true; tracker.observe(null,SystemClock.elapsedRealtime(),System.currentTimeMillis()); dragX = panelParams.x; dragY = panelParams.y; showCloseTarget(); }
                @Override public void dragged(float dx, float dy, float rawX, float rawY) {
                    android.util.DisplayMetrics bounds = screenBounds();
                    panelParams.x = PanelGeometry.clamp(dragX+(int)dx,bounds.widthPixels,panel.windowWidth());
                    panelParams.y = PanelGeometry.clamp(dragY+(int)dy,bounds.heightPixels,panel.windowHeight());
                    if (closeTarget != null) closeTarget.setAlpha(PanelGeometry.closeZone(rawX,rawY,bounds.widthPixels,bounds.heightPixels,bounds.density) ? 1 : .65f);
                    updatePanelLayout();
                }
                @Override public void dragFinished(float rawX, float rawY, boolean cancelled) {
                    android.util.DisplayMetrics bounds = screenBounds(); hideCloseTarget(); savePanel.run();
                    panelMoving = false;
                    if (!cancelled && PanelGeometry.closeZone(rawX,rawY,bounds.widthPixels,bounds.heightPixels,bounds.density)) stopSelf();
                }
                @Override public void resized(float scale) {
                    if (panelParams == null) return;
                    pauseUntil = SystemClock.elapsedRealtime()+350;
                    panelParams.width = panel.windowWidth();
                    panelParams.height = panel.windowHeight();
                    main.post(() -> { if (!ending) { clampPanel(); updatePanelLayout(); } });
                    main.removeCallbacks(savePanel); main.postDelayed(savePanel,250);
                }
                @Override public void history() { startActivity(new Intent(ObserverService.this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); }
                @Override public void close() { stopSelf(); }
            });
        panelParams = new WindowManager.LayoutParams(panel.windowWidth(), panel.windowHeight(),
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE|WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN, PixelFormat.TRANSLUCENT);
        android.util.DisplayMetrics initialBounds = new android.util.DisplayMetrics(); manager.getDefaultDisplay().getRealMetrics(initialBounds);
        panelParams.gravity = Gravity.TOP|Gravity.START;
        panelParams.x = (int)(store.preferences.getFloat("panelX",1)*Math.max(0,initialBounds.widthPixels-panel.windowWidth()));
        panelParams.y = (int)(store.preferences.getFloat("panelY",.025f)*Math.max(0,initialBounds.heightPixels-panel.windowHeight()));
        try { manager.addView(panel, panelParams); } catch (RuntimeException ignored) { panel = null; }
        updatePanelLayout();
    }
    private android.util.DisplayMetrics screenBounds() {
        android.util.DisplayMetrics result = new android.util.DisplayMetrics(); manager.getDefaultDisplay().getRealMetrics(result); return result;
    }
    private void clampPanel() {
        if (panel == null) return; android.util.DisplayMetrics b = screenBounds();
        panelParams.x = PanelGeometry.clamp(panelParams.x,b.widthPixels,panel.windowWidth());
        panelParams.y = PanelGeometry.clamp(panelParams.y,b.heightPixels,panel.windowHeight());
    }
    private void updatePanelLayout() {
        if (panel != null && store != null) {
            android.util.DisplayMetrics b = screenBounds(); double[] r = store.region();
            panelOverFund = PanelGeometry.overlaps(panelParams.x,panelParams.y,panelParams.x+panel.windowWidth(),panelParams.y+panel.windowHeight(),
                (float)r[0]*b.widthPixels,(float)r[1]*b.heightPixels,(float)r[2]*b.widthPixels,(float)r[3]*b.heightPixels);
        }
        if (panel != null) try { manager.updateViewLayout(panel,panelParams); } catch (RuntimeException ignored) {}
    }
    private void showCloseTarget() {
        if (closeTarget != null) return;
        closeTarget = new TextView(this); closeTarget.setText("×"); closeTarget.setTextSize(34); closeTarget.setGravity(Gravity.CENTER);
        closeTarget.setTextColor(Color.rgb(17,28,85)); closeTarget.setContentDescription("Перетащите сюда, чтобы закрыть панель и остановить наблюдение");
        android.graphics.drawable.GradientDrawable shape = new android.graphics.drawable.GradientDrawable();
        shape.setColor(Color.rgb(255,156,191)); shape.setCornerRadius(dp(32)); closeTarget.setBackground(shape);
        WindowManager.LayoutParams p = new WindowManager.LayoutParams(dp(64),dp(64),WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE|WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE|WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,PixelFormat.TRANSLUCENT);
        p.gravity = Gravity.BOTTOM|Gravity.CENTER_HORIZONTAL; p.y = dp(20);
        try { manager.addView(closeTarget,p); } catch (RuntimeException ignored) { closeTarget = null; }
    }
    private void hideCloseTarget() {
        if (closeTarget != null) try { manager.removeView(closeTarget); } catch (RuntimeException ignored) {}
        closeTarget = null;
    }
    private int dp(int value) { return (int)(value*getResources().getDisplayMetrics().density+.5f); }
    private final Runnable savePanel = () -> {
        if (panel == null || store == null) return; android.util.DisplayMetrics b = screenBounds();
        store.preferences.edit().putFloat("panelScale",panel.scale())
            .putFloat("panelX",(float)panelParams.x/Math.max(1,b.widthPixels-panel.windowWidth()))
            .putFloat("panelY",(float)panelParams.y/Math.max(1,b.heightPixels-panel.windowHeight())).apply();
    };
    @Override public void onConfigurationChanged(android.content.res.Configuration configuration) {
        super.onConfigurationChanged(configuration);
        if (panel != null) { clampPanel(); updatePanelLayout(); hideCloseTarget(); panelMoving = false; }
    }
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (ending) return;
            if (panel != null) {
                org.json.JSONObject row = store.events().optJSONObject(0);
                String message = current > 0 ? "Фонд: "+HistoryStore.amount(current)
                    : !store.calibrated() ? "Настройте область" : panelOverFund ? "Панель закрывает фонд"
                    : !captureVisible ? "Игра скрыта"
                    : status.contains("уведомлением") ? "Уведомление закрывает фонд"
                    : "Цифры не читаются · ≡";
                panel.update(row == null ? "Ждём обнуление" : HistoryStore.duration(System.currentTimeMillis()-row.optLong("time")),
                    "Прошлый: "+(row == null ? "—" : HistoryStore.amount(row.optLong("fund"))),message);
            }
            main.postDelayed(this, 1000);
        }
    };
    @Override public void onDestroy() {
        if (store != null) store.preferences.edit().putString("lastDiagnostic", diagnosticSnapshot()).apply();
        savePanel.run(); ending = true; generation++; main.removeCallbacks(tick); main.removeCallbacks(savePanel); hideCloseTarget();
        if (panel != null) try { manager.removeView(panel); } catch (RuntimeException ignored) {}
        if (display != null) display.release();
        if (images != null) images.close();
        if (projection != null) projection.stop();
        if (recognizer != null) recognizer.close();
        if (worker != null) worker.quitSafely();
        synchronized (this) { if (calibrationFrame != null) calibrationFrame.recycle(); calibrationFrame = null; }
        if (active() == this) instance.clear();
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }
}
