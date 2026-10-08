package to.casorin.fountain;

import android.content.Context;
import android.view.MotionEvent;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.ScrollView;

/** Keeps five complete rows visible, including when the system font is enlarged. */
public final class HistoryScrollView extends ScrollView {
    public HistoryScrollView(Context context) { super(context); }

    @Override protected void onMeasure(int widthSpec, int heightSpec) {
        super.onMeasure(widthSpec, heightSpec);
        if (getChildCount() == 0 || !(getChildAt(0) instanceof LinearLayout rows)) return;
        int height = getPaddingTop() + getPaddingBottom();
        for (int i = 0; i < Math.min(5, rows.getChildCount()); i++) {
            View row = rows.getChildAt(i);
            LinearLayout.LayoutParams params = (LinearLayout.LayoutParams)row.getLayoutParams();
            height += row.getMeasuredHeight() + params.topMargin + params.bottomMargin;
        }
        if (height > 0 && height < getMeasuredHeight()) {
            super.onMeasure(widthSpec, MeasureSpec.makeMeasureSpec(height, MeasureSpec.EXACTLY));
        }
    }

    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        if (event.getActionMasked() == MotionEvent.ACTION_DOWN
                && (canScrollVertically(1) || canScrollVertically(-1))) {
            getParent().requestDisallowInterceptTouchEvent(true);
        }
        boolean handled = super.dispatchTouchEvent(event);
        if (event.getActionMasked() == MotionEvent.ACTION_UP
                || event.getActionMasked() == MotionEvent.ACTION_CANCEL) {
            getParent().requestDisallowInterceptTouchEvent(false);
        }
        return handled;
    }
}
