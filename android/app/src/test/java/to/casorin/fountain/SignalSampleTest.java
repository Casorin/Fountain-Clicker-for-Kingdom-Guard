package to.casorin.fountain;

import org.junit.Test;
import static org.junit.Assert.*;
import static org.junit.Assume.*;
import java.io.File;

public class SignalSampleTest {
    private int[] sample(String name) throws Exception {
        String root=System.getProperty("fountain.signalSamples","");
        assumeTrue(!root.isEmpty() && new File(root,name).isFile());
        Object image=Class.forName("javax.imageio.ImageIO").getMethod("read",File.class).invoke(null,new File(root,name));
        Class<?> type=image.getClass();
        int w=(int)type.getMethod("getWidth").invoke(image),h=(int)type.getMethod("getHeight").invoke(image);
        int[] full=(int[])type.getMethod("getRGB",int.class,int.class,int.class,int.class,int[].class,int.class,int.class)
            .invoke(image,0,0,w,h,null,0,w);
        int sh=h*200/w; int[] compact=new int[200*sh];
        for(int y=0;y<sh;y++) for(int x=0;x<200;x++) compact[y*200+x]=full[(y*h/sh)*w+x*w/200];
        return compact;
    }
    @Test public void ordinaryGameHasNoRewardSignal() throws Exception {
        int[] p=sample("updated-before-clicks.png");
        assertFalse(WishPixels.reward(p,200,p.length/200,new double[]{.18,.321,.307,.343}));
        double[] region=WishPixels.balanceRegion(p,200,p.length/200,new double[]{.18,.321,.307,.343});
        assertNotNull(region);assertTrue(region[0]>.75 && region[0]<.85);assertTrue(region[1]<.05);
    }
    @Test public void dailyRewardHasActivitySignal() throws Exception {
        int[] p=sample("updated-click-017.png");
        assertTrue(WishPixels.reward(p,200,p.length/200,new double[]{.18,.321,.307,.343}));
        assertNotNull(WishPixels.balanceRegion(p,200,p.length/200,new double[]{.18,.321,.307,.343}));
    }
}
