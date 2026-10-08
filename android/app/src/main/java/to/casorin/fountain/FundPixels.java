package to.casorin.fountain;

/** Pixel preparation is independent of Android for regression tests. */
final class FundPixels {
    record Mask(byte[] pixels, int left, int top, int right, int bottom, int count, boolean covered) {
        boolean usable() { return count >= 35 && right-left >= 12 && bottom-top >= 8; }
    }
    static boolean isDigit(int color) {
        int r = color >> 16 & 255, g = color >> 8 & 255, b = color & 255;
        return isBrightDigit(color)
            || r >= 70 && g >= 65 && g >= r*.90 && g <= r*1.08 && b <= g*.65;
    }
    private static boolean isBrightDigit(int color) {
        int r = color >> 16 & 255, g = color >> 8 & 255, b = color & 255;
        return r >= 185 && g >= 175 && r-b >= 45 && g-b >= 45;
    }
    static boolean isHeading(int color) {
        int r = color >> 16 & 255, g = color >> 8 & 255, b = color & 255;
        int min = Math.min(r,Math.min(g,b)), max = Math.max(r,Math.max(g,b));
        return min > 155 && max-min < 65 || min > 65 && max-min < min*.28;
    }
    static Mask extract(int[] colors, int width, int height) {
        Mask bright = extract(colors,width,height,false);
        Mask dim = extract(colors,width,height,true);
        // Keep the selective bright mask unless most strokes have been dimmed.
        return bright.usable() && bright.count() >= dim.count()*.65 ? bright : dim;
    }
    private static Mask extract(int[] colors, int width, int height, boolean dimmed) {
        byte[] mask = new byte[colors.length];
        int left = width, top = height, right = 0, bottom = 0, count = 0;
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            int i = y*width+x;
            if (!(dimmed ? isDigit(colors[i]) : isBrightDigit(colors[i]))) continue;
            mask[i] = 1; count++;
            left = Math.min(left,x); top = Math.min(top,y); right = Math.max(right,x+1); bottom = Math.max(bottom,y+1);
        }
        int white = 0;
        for (int y = top; y < bottom; y++) for (int x = left; x < right; x++) {
            int c = colors[y*width+x], r = c >> 16 & 255, g = c >> 8 & 255, b = c & 255;
            if (Math.min(r,Math.min(g,b)) > 170 && Math.max(r,Math.max(g,b))-Math.min(r,Math.min(g,b)) < 30) white++;
        }
        boolean covered = count > 0 && white > (right-left)*(bottom-top)*.1;
        return new Mask(mask,left,top,right,bottom,count,covered);
    }
}
