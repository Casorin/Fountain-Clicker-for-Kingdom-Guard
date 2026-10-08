package to.casorin.fountain;

import org.junit.Test;
import static org.junit.Assert.*;

public class PanelGeometryTest {
    @Test public void clampsToAllFourScreenEdges() {
        assertEquals(0,PanelGeometry.clamp(-30,1080,300));
        assertEquals(780,PanelGeometry.clamp(1200,1080,300));
        assertEquals(400,PanelGeometry.clamp(400,1080,300));
        assertEquals(0,PanelGeometry.clamp(100,200,300));
    }
    @Test public void sizeRemainsReadableAndBounded() {
        assertEquals(.8f,PanelGeometry.scale(.1f),.001f);
        assertEquals(1.65f,PanelGeometry.scale(5),.001f);
        assertEquals(1.1f,PanelGeometry.scale(1.1f),.001f);
    }
    @Test public void closesOnlyNearBottomCross() {
        assertTrue(PanelGeometry.closeZone(540,2290,1080,2340,3));
        assertFalse(PanelGeometry.closeZone(50,2290,1080,2340,3));
        assertFalse(PanelGeometry.closeZone(540,1500,1080,2340,3));
    }
    @Test public void detectsPartialFundOverlapWithoutBlockingOtherPositions() {
        assertTrue(PanelGeometry.overlaps(200,650,400,760,195,675,334,725));
        assertTrue(PanelGeometry.overlaps(100,680,250,750,195,675,334,725));
        assertFalse(PanelGeometry.overlaps(500,650,700,760,195,675,334,725));
        assertFalse(PanelGeometry.overlaps(195,725,334,850,195,675,334,725));
    }
}
