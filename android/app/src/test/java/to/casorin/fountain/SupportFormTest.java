package to.casorin.fountain;

import org.junit.Test;
import static org.junit.Assert.*;
import java.net.URI;
import java.net.URLDecoder;

public class SupportFormTest {
    @Test public void opensExistingForm() {
        URI link = URI.create(SupportForm.prefilledUrl("test"));
        assertEquals("https",link.getScheme());
        assertEquals("docs.google.com",link.getHost());
        assertTrue(link.getPath().endsWith("/viewform"));
        assertTrue(link.getRawQuery().contains("entry.1882575839="));
    }

    @Test public void roundTripsRussianAndSpecialCharacters() throws Exception {
        String report = "Фонтан — диагностика\nКадр: 1080 × 1920\nA&B=1 + ? # 💜";
        String query = URI.create(SupportForm.prefilledUrl(report)).getRawQuery();
        assertEquals(report,URLDecoder.decode(query.substring(query.indexOf(SupportForm.FIELD+"=")
            +SupportForm.FIELD.length()+1),"UTF-8"));
        assertEquals(2,query.split("&").length);
    }

    @Test public void emptyReportStillUsesPrefillField() {
        assertTrue(SupportForm.prefilledUrl("").endsWith(SupportForm.FIELD+"="));
    }
}
