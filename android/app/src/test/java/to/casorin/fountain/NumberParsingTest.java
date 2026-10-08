package to.casorin.fountain;

import org.junit.Test;
import static org.junit.Assert.*;

public class NumberParsingTest {
    @Test public void acceptsOnlyWholeFundNumbers() {
        assertEquals(Long.valueOf(31600), FrameRecognizer.parse("31 600"));
        assertEquals(Long.valueOf(31600), FrameRecognizer.parse("31\u00a0600"));
        assertEquals(Long.valueOf(1201656), FrameRecognizer.parse("1 201 656"));
    }
    @Test public void rejectsLabelsAndDailyCounters() {
        assertNull(FrameRecognizer.parse("0/100"));
        assertNull(FrameRecognizer.parse("4д 14:58:57"));
        assertNull(FrameRecognizer.parse("Призовой фонд 31600"));
        assertNull(FrameRecognizer.parse("31.600"));
        assertNull(FrameRecognizer.parse("12.88млрд"));
        assertNull(FrameRecognizer.parse("31 6OO"));
        assertNull(FrameRecognizer.parse("99999999"));
        assertNull(FrameRecognizer.parse("25(400)"));
        assertNull(FrameRecognizer.parse("25400 reward"));
    }
    @Test public void ignoresOnlyHarmlessEdgeBrackets() {
        assertEquals(Long.valueOf(25400),FrameRecognizer.parse("25 400)"));
        assertEquals(Long.valueOf(25400),FrameRecognizer.parse("<25 400>"));
        assertEquals(Long.valueOf(25400),FrameRecognizer.parse("(25 400)"));
    }
}
