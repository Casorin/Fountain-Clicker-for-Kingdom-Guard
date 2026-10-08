package to.casorin.fountain;

import org.junit.Test;
import static org.junit.Assert.*;

public class AdaptivePollingTest {
    @Test public void normalWithoutActivity() { assertEquals(300,new AdaptivePolling().intervalMs()); }
    @Test public void rewardNeedsTwoFrames() {
        AdaptivePolling p=new AdaptivePolling();p.reward(true,1000);assertFalse(p.fast());
        p.reward(true,1300);assertEquals(150,p.intervalMs());
    }
    @Test public void intermittentRewardIsIgnored() {
        AdaptivePolling p=new AdaptivePolling();p.reward(true,1000);p.reward(false,1200);p.reward(true,1300);assertFalse(p.fast());
    }
    @Test public void staleRewardIsNotConfirmation() {
        AdaptivePolling p=new AdaptivePolling();p.reward(true,1000);p.reward(true,3000);assertFalse(p.fast());
    }
    @Test public void fastUntilConfirmedReset() {
        AdaptivePolling p=new AdaptivePolling();p.reward(true,1000);p.reward(true,1300);p.reward(false,1500);
        p.balance(null,500000);assertTrue(p.fast());p.confirmedReset();assertEquals(300,p.intervalMs());
    }
    @Test public void oldRewardDoesNotRetriggerAfterReset() {
        AdaptivePolling p=new AdaptivePolling();p.reward(true,1000);p.reward(true,1300);p.confirmedReset();
        p.reward(true,1600);p.reward(true,2000);assertFalse(p.fast());
        p.reward(false,2200);p.reward(true,2300);p.reward(true,2500);assertTrue(p.fast());
    }
    @Test public void spendingNeedsConfirmation() {
        AdaptivePolling p=new AdaptivePolling();p.balance(56525L,1000);p.balance(56425L,2000);assertFalse(p.fast());
        p.balance(56425L,2900);assertTrue(p.fast());assertEquals(1,p.balanceTriggers());
    }
    @Test public void continuousSpendingCanConfirm() {
        AdaptivePolling p=new AdaptivePolling();p.balance(56525L,1000);p.balance(56025L,2000);p.balance(55725L,2900);assertTrue(p.fast());
    }
    @Test public void incorrectPriceAndIncreasesDoNotTrigger() {
        AdaptivePolling p=new AdaptivePolling();p.balance(56525L,1000);p.balance(56424L,2000);p.balance(56424L,2900);assertFalse(p.fast());
        p.balance(70000L,3800);p.balance(70000L,4700);assertFalse(p.fast());
    }
    @Test public void recoveredBalanceRejectsCandidate() {
        AdaptivePolling p=new AdaptivePolling();p.balance(56525L,1000);p.balance(56025L,2000);p.balance(56525L,2900);assertFalse(p.fast());
    }
    @Test public void gapDoesNotInferSpending() {
        AdaptivePolling p=new AdaptivePolling();p.balance(56525L,1000);p.balance(56025L,6000);p.balance(56025L,6900);assertFalse(p.fast());
    }
    @Test public void sessionRestartClearsCandidates() {
        AdaptivePolling p=new AdaptivePolling();p.balance(56525L,1000);p.balance(56025L,2000);p.restartSession();
        p.balance(56025L,2900);assertFalse(p.fast());p.reward(true,3000);assertFalse(p.fast());
    }
    @Test public void confirmedResetClearsPendingSpend() {
        AdaptivePolling p=new AdaptivePolling();p.balance(56525L,1000);p.balance(56025L,2000);p.confirmedReset();
        p.balance(56025L,2900);assertFalse(p.fast());
    }
    @Test public void largeOcrDropDoesNotTrigger() {
        AdaptivePolling p=new AdaptivePolling();p.balance(56525L,1000);p.balance(565L,2000);p.balance(565L,2900);assertFalse(p.fast());
    }
    @Test public void resetDoesNotReactToPreResetSpending() {
        AdaptivePolling p=new AdaptivePolling();p.balance(56525L,1000);p.reward(true,1100);p.reward(true,1400);
        p.confirmedReset();p.balance(56025L,1500);p.balance(56025L,2400);assertFalse(p.fast());
    }
    @Test public void missingFundDoesNotCountAsConfirmedReset() {
        AdaptivePolling p=new AdaptivePolling();ResetTracker tracker=new ResetTracker();
        tracker.observe(50000L,1000,100000);p.reward(true,1000);p.reward(true,1300);
        for(long t=1400;t<25000;t+=150) assertNull(tracker.observe(null,t,100000+t));
        assertTrue(p.fast());
    }
    @Test public void resetStillRequiresThreeReadableFrames() {
        AdaptivePolling p=new AdaptivePolling();ResetTracker tracker=new ResetTracker();
        tracker.observe(50000L,1000,100000);p.reward(true,1000);p.reward(true,1300);
        assertNull(tracker.observe(15000L,1400,100400));assertTrue(p.fast());
        assertNull(tracker.observe(15100L,1550,100550));assertTrue(p.fast());
        assertNotNull(tracker.observe(15200L,1700,100700));p.confirmedReset();assertFalse(p.fast());
    }
}
