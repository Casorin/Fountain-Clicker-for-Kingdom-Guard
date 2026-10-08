package to.casorin.fountain;

import android.graphics.*;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.latin.TextRecognizerOptions;
import com.google.android.gms.tasks.Task;
import com.google.android.gms.tasks.Tasks;
import com.google.mlkit.vision.text.Text;
import java.util.function.Consumer;

final class FrameRecognizer implements AutoCloseable {
    record Result(Long value, String detail, String rawText, String maskText, String alternateText) {
        Result(Long value,String detail) { this(value,detail,"","",""); }
    }
    private final TextRecognizer reader = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS);
    private volatile boolean closed;

    void readBalance(Bitmap frame,double[] region,Consumer<Long> done) {
        if(region==null) { done.accept(null); return; }
        Rect r=rect(frame,region);
        if(r.width()<12 || r.height()<8) { done.accept(null); return; }
        Bitmap crop=Bitmap.createBitmap(frame,r.left,r.top,r.width(),r.height());
        Bitmap raw=Bitmap.createScaledBitmap(crop,r.width()*3,r.height()*3,true);
        if(crop!=raw && crop!=frame) crop.recycle();
        Bitmap mask=Bitmap.createBitmap(raw.getWidth(),raw.getHeight(),Bitmap.Config.ARGB_8888);
        int[] colors=new int[raw.getWidth()*raw.getHeight()];
        raw.getPixels(colors,0,raw.getWidth(),0,0,raw.getWidth(),raw.getHeight());
        for(int i=0;i<colors.length;i++) colors[i]=WishPixels.white(colors[i]) ? Color.BLACK : Color.WHITE;
        mask.setPixels(colors,0,raw.getWidth(),0,0,raw.getWidth(),raw.getHeight());
        process(raw).addOnSuccessListener(first -> {
            Long value=WishPixels.parseBalance(first.getText());
            process(mask).addOnSuccessListener(second -> {
                Long other=WishPixels.parseBalance(second.getText());
                done.accept(!closed && value!=null && value.equals(other) ? value : null);
            }).addOnFailureListener(error -> done.accept(null))
                .addOnCompleteListener(task -> { raw.recycle();mask.recycle(); });
        }).addOnFailureListener(error -> { raw.recycle();mask.recycle();done.accept(null); });
    }

    void readDetailed(Bitmap frame, double[] region, Consumer<Result> done) {
        Rect selected = rect(frame, region);
        if (selected.width() < 12 || selected.height() < 8) { done.accept(new Result(null,"Рамка слишком мала")); return; }
        // Finger-drawn boxes need tolerance so digit strokes are not clipped.
        Rect r = new Rect(Math.max(0,selected.left-selected.width()/6), Math.max(0,selected.top-selected.height()/3),
            Math.min(frame.getWidth(),selected.right+selected.width()/3), Math.min(frame.getHeight(),selected.bottom+selected.height()/3));
        int[] pixels = new int[r.width()*r.height()];
        frame.getPixels(pixels,0,r.width(),r.left,r.top,r.width(),r.height());
        FundPixels.Mask data = FundPixels.extract(pixels,r.width(),r.height());
        if (!data.usable()) { done.accept(new Result(null,"В рамке не найдены жёлтые цифры")); return; }
        if (data.covered()) { done.accept(new Result(null,"Цифры перекрыты уведомлением")); return; }
        int padding = 8, w = data.right()-data.left(), h = data.bottom()-data.top();
        Bitmap raw = Bitmap.createBitmap(w+padding*2,h+padding*2,Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(raw); canvas.drawColor(Color.BLACK);
        Paint paint = new Paint(Paint.FILTER_BITMAP_FLAG);
        canvas.drawBitmap(frame,new Rect(r.left+data.left(),r.top+data.top(),r.left+data.right(),r.top+data.bottom()),
            new Rect(padding,padding,padding+w,padding+h),paint);
        Bitmap mask = Bitmap.createBitmap(raw.getWidth(),raw.getHeight(),Bitmap.Config.ARGB_8888);
        mask.eraseColor(Color.WHITE);
        for (int y = data.top(); y < data.bottom(); y++) for (int x = data.left(); x < data.right(); x++) {
            if (data.pixels()[y*r.width()+x] != 0) mask.setPixel(x-data.left()+padding,y-data.top()+padding,Color.BLACK);
        }
        Bitmap enlarged = Bitmap.createScaledBitmap(raw,raw.getWidth()*3,raw.getHeight()*3,true);
        Bitmap masked = Bitmap.createScaledBitmap(mask,mask.getWidth()*3,mask.getHeight()*3,false);
        Bitmap alternate = Bitmap.createBitmap(masked.getWidth(),masked.getHeight(),Bitmap.Config.ARGB_8888);
        int[] inverse = new int[masked.getWidth()*masked.getHeight()];
        masked.getPixels(inverse,0,masked.getWidth(),0,0,masked.getWidth(),masked.getHeight());
        for (int i = 0; i < inverse.length; i++) inverse[i] = inverse[i] == Color.BLACK ? Color.WHITE : Color.BLACK;
        alternate.setPixels(inverse,0,masked.getWidth(),0,0,masked.getWidth(),masked.getHeight());
        raw.recycle(); mask.recycle();
        process(enlarged).addOnSuccessListener(text -> {
            Long first = parse(text.getText());
            if (closed) {
                enlarged.recycle(); masked.recycle(); alternate.recycle();
                done.accept(new Result(null,"Не удалось прочитать цифры: проверьте рамку")); return;
            }
            process(masked).addOnSuccessListener(second -> {
                Long value = parse(second.getText());
                if (first != null && first.equals(value) && !closed) {
                    done.accept(new Result(value,"Фонд прочитан",text.getText(),second.getText(),""));
                    enlarged.recycle(); masked.recycle(); alternate.recycle();
                    return;
                }
                // A second polarity can recover glyphs rejected by the first mask.
                process(alternate).addOnSuccessListener(third -> {
                    Long other = parse(third.getText());
                    boolean agreed = other != null && (other.equals(first) || other.equals(value)) && !closed;
                    done.accept(new Result(agreed ? other : null,agreed ? "Фонд прочитан" : "Проверки цифр не совпали",
                        text.getText(),second.getText(),third.getText()));
                }).addOnFailureListener(error -> done.accept(new Result(null,"Ошибка распознавания")))
                    .addOnCompleteListener(task -> { enlarged.recycle(); masked.recycle(); alternate.recycle(); });
            }).addOnFailureListener(error -> done.accept(new Result(null,"Ошибка распознавания")))
                .addOnFailureListener(error -> { enlarged.recycle(); masked.recycle(); alternate.recycle(); });
        }).addOnFailureListener(error -> {
            enlarged.recycle(); masked.recycle(); alternate.recycle(); done.accept(new Result(null,"Ошибка распознавания"));
        });
    }
    static Long parse(String text) {
        String digits = text.replaceAll("[\\s\\p{Z}]", "");
        // Masked gold background can be recognized as a bracket beside the number.
        digits = digits.replaceAll("^[()<>]+|[()<>]+$", "");
        if (!digits.matches("[0-9]{4,7}")) return null;
        try { long value = Long.parseLong(digits); return value > 0 ? value : null; }
        catch (NumberFormatException ignored) { return null; }
    }
    static Rect rect(Bitmap frame, double[] region) {
        int left = (int)(Math.max(0,Math.min(1,region[0]))*frame.getWidth());
        int top = (int)(Math.max(0,Math.min(1,region[1]))*frame.getHeight());
        int right = (int)(Math.max(0,Math.min(1,region[2]))*frame.getWidth());
        int bottom = (int)(Math.max(0,Math.min(1,region[3]))*frame.getHeight());
        return new Rect(left,top,right,bottom);
    }
    private synchronized Task<Text> process(Bitmap image) {
        if (closed) return Tasks.forException(new IllegalStateException("Recognizer closed"));
        try { return reader.process(InputImage.fromBitmap(image,0)); }
        catch (RuntimeException error) { return Tasks.forException(error); }
    }
    @Override public synchronized void close() { closed = true; reader.close(); }
}
