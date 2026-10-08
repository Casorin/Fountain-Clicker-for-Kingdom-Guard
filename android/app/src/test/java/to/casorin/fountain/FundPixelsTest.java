package to.casorin.fountain;

import org.junit.Test;
import java.util.Arrays;
import static org.junit.Assert.*;

public class FundPixelsTest {
    @Test public void keepsYellowDigitsUnderDarkTranslucentToast() {
        assertTrue(FundPixels.isDigit(0xff8c844a));
        assertTrue(FundPixels.isDigit(0xff726b3c));
        assertFalse(FundPixels.isDigit(0xff88723e));
        assertFalse(FundPixels.isDigit(0xffbba477));
    }
    @Test public void keepsDimmedHeadingButRejectsYellowAndWarmBackground() {
        assertTrue(FundPixels.isHeading(0xff92918b));
        assertTrue(FundPixels.isHeading(0xff72716d));
        assertFalse(FundPixels.isHeading(0xff8c844a));
        assertFalse(FundPixels.isHeading(0xff88723e));
    }
    @Test public void keepsBrightYellowDigitPixels() {
        assertTrue(FundPixels.isDigit(0xfffff186));
        assertTrue(FundPixels.isDigit(0xffeee577));
    }
    @Test public void rejectsWarmBackgroundAndBlueDiamond() {
        assertFalse(FundPixels.isDigit(0xff88723e));
        assertFalse(FundPixels.isDigit(0xffbba477));
        assertFalse(FundPixels.isDigit(0xff48c3ee));
        assertFalse(FundPixels.isDigit(0xffff99bf));
        assertFalse(FundPixels.isDigit(0xffeeeeee));
        assertFalse(FundPixels.isDigit(0xff9fffe4));
    }
    @Test public void blueMarginDoesNotRejectWholeImage() {
        int[] colors = new int[40*24]; Arrays.fill(colors,0xff48c3ee);
        for (int y = 6; y < 18; y++) for (int x = 10; x < 30; x++) colors[y*40+x] = 0xfffff186;
        FundPixels.Mask m = FundPixels.extract(colors,40,24);
        assertTrue(m.usable()); assertEquals(240,m.count());
        assertEquals(10,m.left()); assertEquals(30,m.right()); assertEquals(6,m.top()); assertEquals(18,m.bottom());
    }
    @Test public void whiteNotificationAloneIsNotFund() {
        int[] colors = new int[40*24]; Arrays.fill(colors,0xffeeeeee);
        assertFalse(FundPixels.extract(colors,40,24).usable());
    }
    @Test public void isolatedYellowNoiseIsNotEnough() {
        int[] colors = new int[40*24]; colors[20] = 0xfffff186;
        assertFalse(FundPixels.extract(colors,40,24).usable());
    }
    @Test public void notificationInsideDigitAreaIsRejected() {
        int[] colors = new int[40*24];
        for (int y = 6; y < 18; y++) for (int x = 10; x < 30; x++) colors[y*40+x] = 0xfffff186;
        for (int y = 8; y < 16; y++) for (int x = 14; x < 24; x++) colors[y*40+x] = 0xffeeeeee;
        FundPixels.Mask m = FundPixels.extract(colors,40,24);
        assertTrue(m.usable()); assertTrue(m.covered());
    }
}
