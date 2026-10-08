package to.casorin.fountain;

import android.graphics.Bitmap;
import java.util.Base64;

/** Checks the stable white fund heading, not the animated background or balance. */
final class FountainGuard {
    private static final int WIDTH = 64, HEIGHT = 20;
    static byte[] signature(Bitmap frame, double[] region) {
        return signature(frame,region,false);
    }
    private static byte[] signature(Bitmap frame, double[] region, boolean dimmed) {
        double w = region[2]-region[0], h = region[3]-region[1];
        double left = Math.max(0, region[0]-w*.8), right = Math.min(1, region[2]+w*.2);
        double top = Math.max(0, region[1]-h*1.7), bottom = Math.max(top, region[1]-h*.25);
        byte[] result = new byte[WIDTH*HEIGHT];
        for (int y = 0; y < HEIGHT; y++) for (int x = 0; x < WIDTH; x++) {
            int px = Math.min(frame.getWidth()-1, (int)((left+(right-left)*(x+.5)/WIDTH)*frame.getWidth()));
            int py = Math.min(frame.getHeight()-1, (int)((top+(bottom-top)*(y+.5)/HEIGHT)*frame.getHeight()));
            int c = frame.getPixel(px,py), r = c >> 16 & 255, g = c >> 8 & 255, b = c & 255;
            int min = Math.min(r,Math.min(g,b)), max = Math.max(r,Math.max(g,b));
            result[y*WIDTH+x] = (byte)((dimmed ? FundPixels.isHeading(c) : min > 155 && max-min < 65) ? 1 : 0);
        }
        return result;
    }
    static boolean usable(byte[] signature) {
        int count = 0; for (byte value : signature) count += value;
        return count >= 30 && count < signature.length*.6;
    }
    static String encode(byte[] signature) { return Base64.getEncoder().encodeToString(signature); }
    static boolean matches(Bitmap frame, double[] region, String saved) {
        try {
            byte[] reference = Base64.getDecoder().decode(saved), actual = signature(frame, region);
            if (reference.length != actual.length) return false;
            if (matches(reference,actual)) return true;
            int bright = 0, expected = 0;
            for (byte value : actual) bright += value;
            for (byte value : reference) expected += value;
            return bright < expected*.7 && matches(reference,signature(frame,region,true));
        } catch (IllegalArgumentException ignored) { return false; }
    }
    private static boolean matches(byte[] reference,byte[] actual) {
        return usable(actual) && coverage(reference,actual) >= .72 && coverage(actual,reference) >= .62;
    }
    private static double coverage(byte[] source, byte[] target) {
        int total = 0, found = 0;
        for (int y = 0; y < HEIGHT; y++) for (int x = 0; x < WIDTH; x++) {
            if (source[y*WIDTH+x] == 0) continue;
            total++; boolean nearby = false;
            for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
                int nx = x+dx, ny = y+dy;
                if (nx >= 0 && nx < WIDTH && ny >= 0 && ny < HEIGHT && target[ny*WIDTH+nx] != 0) nearby = true;
            }
            if (nearby) found++;
        }
        return total == 0 ? 0 : (double)found/total;
    }
}
