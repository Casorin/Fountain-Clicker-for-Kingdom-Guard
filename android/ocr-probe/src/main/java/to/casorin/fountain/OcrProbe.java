package to.casorin.fountain;

import android.app.Instrumentation;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Offline native OCR check; never obtains screen/input permissions. */
public final class OcrProbe extends Instrumentation {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final List<String> output = new ArrayList<>();
    private String[] files;
    private FrameRecognizer reader;
    private double[] region;
    private int index;
    private String anchor;
    private boolean signals;

    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        anchor = args.getString("anchor", "");
        signals = Boolean.parseBoolean(args.getString("signals","false"));
        region = new double[]{Double.parseDouble(args.getString("left", ".18270981")),
            Double.parseDouble(args.getString("top", ".32157174")),
            Double.parseDouble(args.getString("right", ".30718532")),
            Double.parseDouble(args.getString("bottom", ".34281301"))};
        start();
    }
    @Override public void onStart() {
        try {
            files = getTargetContext().getAssets().list("");
            files = Arrays.stream(files).filter(s -> s.endsWith(".png")).sorted().toArray(String[]::new);
            main.post(() -> { reader = new FrameRecognizer(); next(); });
        } catch (Exception error) { complete(error.toString()); }
    }
    private void next() {
        if (index >= files.length) { reader.close(); complete(String.join("\n",output)); return; }
        String file = files[index++];
        try (InputStream stream = getTargetContext().getAssets().open(file)) {
            Bitmap image = BitmapFactory.decodeStream(stream);
            if(signals) {
                Bitmap compact=Bitmap.createScaledBitmap(image,200,image.getHeight()*200/image.getWidth(),false);
                int[] pixels=new int[compact.getWidth()*compact.getHeight()];
                compact.getPixels(pixels,0,compact.getWidth(),0,0,compact.getWidth(),compact.getHeight());
                boolean reward=WishPixels.reward(pixels,compact.getWidth(),compact.getHeight(),region);
                double[] balance=WishPixels.balanceRegion(pixels,compact.getWidth(),compact.getHeight(),region);
                compact.recycle();
                reader.readBalance(image,balance,value -> main.post(() -> {
                    output.add(file+": balance="+value+"; reward="+reward+"; region="+Arrays.toString(balance));
                    image.recycle();next();
                }));
                return;
            }
            boolean heading = FountainGuard.matches(image,region,anchor);
            reader.readDetailed(image,region,result -> main.post(() -> {
                output.add(file+": "+result.value()+"; heading="+heading+"; "+result.detail()+"; raw="+result.rawText()
                    +"; mask="+result.maskText()+"; alternate="+result.alternateText());
                image.recycle(); next();
            }));
        } catch (Exception error) { output.add(file+": "+error); next(); }
    }
    private void complete(String message) {
        Bundle result = new Bundle(); result.putString("stream", "\n"+message+"\n"); finish(0,result);
    }
}
