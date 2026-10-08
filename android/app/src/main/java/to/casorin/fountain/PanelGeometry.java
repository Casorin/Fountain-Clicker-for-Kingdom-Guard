package to.casorin.fountain;

final class PanelGeometry {
    static float scale(float value) { return Math.max(.8f,Math.min(1.65f,value)); }
    static int clamp(int position, int screen, int panel) { return Math.max(0,Math.min(Math.max(0,screen-panel),position)); }
    static boolean closeZone(float x, float y, int width, int height, float density) {
        return Math.abs(x-width/2f) <= 80*density && y >= height-110*density;
    }
    static boolean overlaps(float left, float top, float right, float bottom, float otherLeft, float otherTop, float otherRight, float otherBottom) {
        return left < otherRight && right > otherLeft && top < otherBottom && bottom > otherTop;
    }
}
