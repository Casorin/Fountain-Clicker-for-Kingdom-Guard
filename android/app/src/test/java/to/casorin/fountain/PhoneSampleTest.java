package to.casorin.fountain;

import org.junit.Test;
import static org.junit.Assert.*;
import static org.junit.Assume.*;
import java.io.File;

public class PhoneSampleTest {
    @Test public void separatesDigitsFromActualSamsungBackground() throws Exception {
        String path = System.getProperty("fountain.sample","");
        assumeTrue(!path.isEmpty() && new File(path).isFile());
        // Android's compile-time API has no java.desktop; the host test JVM does.
        Object image = Class.forName("javax.imageio.ImageIO").getMethod("read",File.class).invoke(null,new File(path));
        Class<?> type = image.getClass();
        assertEquals(1080,type.getMethod("getWidth").invoke(image));
        assertEquals(2340,type.getMethod("getHeight").invoke(image));
        int width = 208, height = 81;
        int[] colors = (int[])type.getMethod("getRGB",int.class,int.class,int.class,int.class,int[].class,int.class,int.class)
            .invoke(image,172,660,width,height,null,0,width);
        FundPixels.Mask mask = FundPixels.extract(colors,width,height);
        assertTrue(mask.usable()); assertEquals(2192,mask.count());
        assertEquals(31,mask.left()); assertEquals(24,mask.top());
        assertEquals(154,mask.right()); assertEquals(59,mask.bottom());
    }
}
