package to.casorin.fountain;

import android.content.Context;
import android.graphics.*;
import android.text.TextUtils;
import android.view.*;

/** A small overlay without the platform Button minimum sizes. */
@android.annotation.SuppressLint("ViewConstructor") // Constructed only by the service, never inflated from XML.
final class FloatingPanel extends View {
    interface Listener {
        void dragStarted();
        void dragged(float dx, float dy, float rawX, float rawY);
        void dragFinished(float rawX, float rawY, boolean cancelled);
        void resized(float scale);
        void history();
        void close();
    }
    private final Listener listener;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final android.text.TextPaint textPaint = new android.text.TextPaint();
    private final RectF background = new RectF(), stop = new RectF(), resize = new RectF();
    private final RectF[] actions = {new RectF(),new RectF(),new RectF(),new RectF()};
    private final float density;
    private final int ink, muted, blue;
    private final ScaleGestureDetector scaler;
    private float size, downX, downY, downScale, downWidth, tapX, tapY;
    private boolean expanded, dragging, resizing, pinched;
    private String timer = "Ждём обнуление", previous = "Прошлый: —", status = "Подготовка";

    FloatingPanel(Context context, float scale, boolean dark, Listener listener) {
        super(context); this.listener = listener; size = PanelGeometry.scale(scale);
        density = getResources().getDisplayMetrics().density;
        ink = Color.parseColor(dark ? "#F2F5FF" : "#111C55");
        muted = Color.parseColor(dark ? "#B7CEE5" : "#526DA4");
        blue = Color.parseColor(dark ? "#284965" : "#DEF2FF");
        setClickable(true); setFocusable(true);
        scaler = new ScaleGestureDetector(context,new ScaleGestureDetector.SimpleOnScaleGestureListener() {
            @Override public boolean onScaleBegin(ScaleGestureDetector detector) {
                pinched = true;
                if (dragging) { listener.dragFinished(0,0,true); dragging = false; }
                return true;
            }
            @Override public boolean onScale(ScaleGestureDetector detector) { setSize(size*detector.getScaleFactor()); return true; }
        });
    }
    int windowWidth() { return Math.round(168*density*size); }
    int windowHeight() { return Math.round(unit(expanded ? 99 : 70)); }
    float scale() { return size; }
    private float unit(float value) { return value*density*size; }
    private void setSize(float value) {
        size = PanelGeometry.scale(value); requestLayout(); invalidate(); listener.resized(size);
    }
    void update(String time, String fund, String message) {
        timer = time; previous = fund; status = message;
        setContentDescription(time+". "+fund+". "+message+". Нажмите для кнопок: уменьшить, увеличить, история, закрыть. Панель можно перетащить.");
        invalidate();
    }
    @Override protected void onMeasure(int widthSpec, int heightSpec) {
        setMeasuredDimension(resolveSize(windowWidth(),widthSpec),resolveSize(windowHeight(),heightSpec));
    }
    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        background.set(1,1,getWidth()-1,getHeight()-1);
        paint.setStyle(Paint.Style.FILL); paint.setColor(blue); canvas.drawRoundRect(background,unit(13),unit(13),paint);
        paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(density); paint.setColor(Color.rgb(170,211,239));
        canvas.drawRoundRect(background,unit(13),unit(13),paint); paint.setStyle(Paint.Style.FILL);
        stop.set(getWidth()-unit(47),unit(7),getWidth()-unit(8),unit(29));
        paint.setColor(Color.rgb(255,156,191)); canvas.drawRoundRect(stop,unit(7),unit(7),paint);
        drawCentered(canvas,"Стоп",stop,10,Color.rgb(17,28,85),true);
        drawText(canvas,timer,unit(9),unit(23),stop.left-unit(14),14,ink,true);
        drawText(canvas,previous,unit(9),unit(43),getWidth()-unit(18),11,ink,false);
        drawText(canvas,status,unit(9),unit(59),getWidth()-unit(33),9,muted,false);
        if (expanded) {
            String[] titles = {"−","+","≡","×"};
            float total = unit(4*27+3*5), left = (getWidth()-total)/2;
            for (int i = 0; i < actions.length; i++) {
                actions[i].set(left+i*unit(32),unit(68),left+i*unit(32)+unit(27),unit(92));
                paint.setColor(i == 3 ? Color.rgb(255,156,191) : Color.argb(110,159,211,249));
                canvas.drawRoundRect(actions[i],unit(6),unit(6),paint);
                drawCentered(canvas,titles[i],actions[i],16,i == 3 ? Color.rgb(17,28,85) : ink,true);
            }
        }
        resize.set(getWidth()-unit(21),getHeight()-unit(21),getWidth(),getHeight());
        paint.setColor(Color.rgb(229,117,162)); paint.setStrokeWidth(unit(1.5f));
        canvas.drawLine(getWidth()-unit(14),getHeight()-unit(6),getWidth()-unit(6),getHeight()-unit(14),paint);
        canvas.drawLine(getWidth()-unit(9),getHeight()-unit(5),getWidth()-unit(5),getHeight()-unit(9),paint);
    }
    private void drawText(Canvas canvas, String value, float x, float baseline, float maxWidth, int font, int color, boolean bold) {
        paint.setTypeface(Typeface.create("sans-serif-condensed",bold ? Typeface.BOLD : Typeface.NORMAL));
        paint.setTextSize(unit(font)); paint.setColor(color);
        textPaint.set(paint);
        String clipped = TextUtils.ellipsize(value,textPaint,Math.max(1,maxWidth),TextUtils.TruncateAt.END).toString();
        canvas.drawText(clipped,x,baseline,paint);
    }
    private void drawCentered(Canvas canvas, String value, RectF box, int font, int color, boolean bold) {
        paint.setTypeface(Typeface.create("sans-serif-condensed",bold ? Typeface.BOLD : Typeface.NORMAL));
        paint.setTextSize(unit(font)); paint.setColor(color);
        canvas.drawText(value,box.centerX()-paint.measureText(value)/2,box.centerY()-(paint.ascent()+paint.descent())/2,paint);
    }
    @Override public boolean onTouchEvent(MotionEvent event) {
        scaler.onTouchEvent(event);
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) {
            downX = event.getRawX(); downY = event.getRawY(); downScale = size; downWidth = getWidth();
            tapX = event.getX(); tapY = event.getY();
            dragging = pinched = false; resizing = resize.contains(tapX,tapY); return true;
        }
        if (action == MotionEvent.ACTION_POINTER_DOWN) {
            pinched = true;
            if (dragging) { listener.dragFinished(0,0,true); dragging = false; }
            return true;
        }
        if (action == MotionEvent.ACTION_MOVE && !pinched) {
            float dx = event.getRawX()-downX, dy = event.getRawY()-downY;
            if (resizing) { setSize(downScale*(1+(dx+dy*.6f)/Math.max(1,downWidth))); return true; }
            if (!dragging && Math.hypot(dx,dy) > ViewConfiguration.get(getContext()).getScaledTouchSlop()) {
                dragging = true; listener.dragStarted();
            }
            if (dragging) listener.dragged(dx,dy,event.getRawX(),event.getRawY());
            return true;
        }
        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            if (dragging) listener.dragFinished(event.getRawX(),event.getRawY(),action == MotionEvent.ACTION_CANCEL);
            else if (!pinched && !resizing && action == MotionEvent.ACTION_UP) performClick();
            dragging = false; return true;
        }
        return true;
    }
    @Override public boolean performClick() {
        super.performClick();
        if (stop.contains(tapX,tapY)) { listener.close(); return true; }
        if (expanded) for (int i = 0; i < actions.length; i++) if (actions[i].contains(tapX,tapY)) {
            if (i == 0) setSize(size-.1f);
            if (i == 1) setSize(size+.1f);
            if (i == 2) listener.history();
            if (i == 3) listener.close();
            return true;
        }
        expanded = !expanded; requestLayout(); invalidate(); listener.resized(size); return true;
    }
}
