package to.casorin.fountain;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.AdaptiveIconDrawable;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.os.Bundle;
import android.text.Spanned;
import android.text.TextPaint;
import android.text.style.ClickableSpan;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Native checks run in an isolated test APK; they never modify saved history. */
public final class UiChecks extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            runOnMainSync(() -> {
                for (int rows : new int[]{0,1,5,6,200}) {
                    for (float font : new float[]{1,1.5f,2}) checkRows(rows,font);
                }
                String report = DiagnosticReport.create(getTargetContext(),new HistoryStore(getTargetContext()));
                require(report.contains("Кадр:") || report.contains("Данные сессии пока отсутствуют"),"capture diagnostics");
                require(!report.contains("Прочитано:") && !report.contains("Прошлый фонд:"),"private balances excluded");
                require(SupportForm.prefilledUrl(report).contains(SupportForm.FIELD+"="),"report prefilled");
            });
            Activity activity = startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            runOnMainSync(() -> {
                View root = activity.getWindow().getDecorView();
                require(hasText(root,"Инструкция и разрешения"),"information button");
                require(hasText(root,"Настроить область фонда"),"settings button");
                require(hasText(root,"Сообщить об ошибке"),"report button");
                require(hasText(root,"на кофе💜"),"footer links");
                HistoryScrollView table = findTable(root);
                require(table != null,"history viewport");
                GradientDrawable thumb = (GradientDrawable)table.getVerticalScrollbarThumbDrawable();
                require(thumb.getColor().getDefaultColor()==android.graphics.Color.parseColor("#FF9CBF"),"pink scrollbar");
                checkFooter(root);
                android.graphics.drawable.Drawable icon=getTargetContext().getApplicationInfo().loadIcon(getTargetContext().getPackageManager());
                require(icon instanceof AdaptiveIconDrawable,"adaptive launcher icon");
                if(android.os.Build.VERSION.SDK_INT>=33) require(((AdaptiveIconDrawable)icon).getMonochrome()!=null,"themed icon");
                Bitmap preview=Bitmap.createBitmap(384,384,Bitmap.Config.ARGB_8888);
                icon.setBounds(0,0,384,384);icon.draw(new Canvas(preview));
                try(java.io.FileOutputStream output=new java.io.FileOutputStream(
                        new java.io.File(getTargetContext().getExternalCacheDir(),"launcher-icon-preview.png"))) {
                    preview.compress(Bitmap.CompressFormat.PNG,100,output);
                } catch(java.io.IOException error) { throw new IllegalStateException(error); }
                finally { preview.recycle(); }
            });
            result.putString("stream","OK: 15 viewport cases (0/1/5/6/200 rows, three font sizes), pink scrollbar, footer, diagnostics and UI labels. History unchanged.\n");
            finish(Activity.RESULT_OK,result);
        } catch (Throwable error) {
            result.putString("stream","FAIL: "+error+"\n");
            finish(Activity.RESULT_CANCELED,result);
        }
    }

    private void checkRows(int count,float font) {
        float density = getTargetContext().getResources().getDisplayMetrics().density;
        HistoryScrollView viewport = new HistoryScrollView(getTargetContext());
        LinearLayout rows = new LinearLayout(getTargetContext()); rows.setOrientation(LinearLayout.VERTICAL);
        for (int i=0;i<count;i++) {
            LinearLayout row = new LinearLayout(getTargetContext()); row.setMinimumHeight((int)(56*density));
            TextView time = new TextView(getTargetContext()); time.setTextSize(12*font);
            time.setText(i == 0 ? "08.10 10:45:00\nПоследнее" : "08.10 10:45:00");
            time.setPadding(0,(int)(10*density),0,(int)(10*density));
            row.addView(time,new LinearLayout.LayoutParams(0,-2,1));
            TextView fund = new TextView(getTargetContext()); fund.setTextSize(12*font); fund.setText("1 000 000");
            row.addView(fund,new LinearLayout.LayoutParams(0,-2,1.2f));
            TextView interval = new TextView(getTargetContext()); interval.setTextSize(12*font); interval.setText("Неизвестно");
            row.addView(interval,new LinearLayout.LayoutParams(0,-2,1.1f));
            rows.addView(row);
        }
        viewport.addView(rows);
        viewport.measure(View.MeasureSpec.makeMeasureSpec((int)(320*density),View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(0,View.MeasureSpec.UNSPECIFIED));
        viewport.layout(0,0,viewport.getMeasuredWidth(),viewport.getMeasuredHeight());
        int expected=0;
        for(int i=0;i<Math.min(5,count);i++) expected+=rows.getChildAt(i).getMeasuredHeight();
        require(expected==viewport.getMeasuredHeight(),"five complete rows: "+count+" / font "+font);
        require(rows.getChildCount()==count,"all rows preserved");
        require(viewport.canScrollVertically(1)==(count>5),"scroll beyond five rows");
    }

    private boolean hasText(View view,String value) {
        if (view instanceof TextView label && label.getText().toString().contains(value)) return true;
        if (view instanceof ViewGroup group) for(int i=0;i<group.getChildCount();i++) if(hasText(group.getChildAt(i),value)) return true;
        return false;
    }
    private HistoryScrollView findTable(View view) {
        if(view instanceof HistoryScrollView table) return table;
        if(view instanceof ViewGroup group) for(int i=0;i<group.getChildCount();i++) {
            HistoryScrollView table=findTable(group.getChildAt(i)); if(table!=null) return table;
        }
        return null;
    }
    private void checkFooter(View view) {
        if(view instanceof TextView text && text.getText().toString().startsWith("Created by:")) {
            require(text.getText() instanceof Spanned,"clickable footer");
            Spanned footer=(Spanned)text.getText();
            ClickableSpan[] links=footer.getSpans(0,footer.length(),ClickableSpan.class);
            require(links.length==2,"two footer links");
            for(ClickableSpan link:links) {
                require(footer.getSpanStart(link)>=12,"prefix is ordinary text");
                TextPaint paint=new TextPaint(); link.updateDrawState(paint);
                require(paint.getColor()==android.graphics.Color.parseColor("#FFA8CA"),"light pink link");
            }
        }
        if(view instanceof ViewGroup group) for(int i=0;i<group.getChildCount();i++) checkFooter(group.getChildAt(i));
    }
    private static void require(boolean condition,String message) { if(!condition) throw new AssertionError(message); }
}
