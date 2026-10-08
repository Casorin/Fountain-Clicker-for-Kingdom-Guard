package to.casorin.fountain;

import org.junit.Test;
import static org.junit.Assert.*;

public class WishPixelsTest {
    @Test public void parsesOnlyWholeBalanceNumbers() {
        assertEquals(Long.valueOf(56525),WishPixels.parseBalance("56 525"));
        assertEquals(Long.valueOf(0),WishPixels.parseBalance("0"));
        assertEquals(Long.valueOf(1201656),WishPixels.parseBalance("1\u00a0201\u00a0656"));
        for(String s:new String[]{"56K","1/100","Получить X1","56 + 525","1234567890",""}) assertNull(WishPixels.parseBalance(s));
    }
    @Test public void emptyScreenDoesNotTrigger() {
        assertFalse(WishPixels.reward(new int[200*360],200,360,new double[]{.18,.32,.30,.34}));
        assertNull(WishPixels.balanceRegion(new int[200*360],200,360,new double[]{.18,.32,.30,.34}));
    }
    @Test public void detectsTwoLongWhiteTextBands() {
        int[] image=new int[200*360];
        for(int y:new int[]{110,111,112,125,126,127}) for(int x=80;x<169;x+=2) image[y*200+x]=0xffffffff;
        assertTrue(WishPixels.reward(image,200,360,new double[]{.18,.32,.30,.34}));
    }
    @Test public void oneWhiteRowIsNotEnough() {
        int[] image=new int[200*360];
        for(int y=110;y<113;y++) for(int x=80;x<169;x+=2) image[y*200+x]=0xffffffff;
        assertFalse(WishPixels.reward(image,200,360,new double[]{.18,.32,.30,.34}));
    }
}
