package to.casorin.fountain;

/** Activity changes sampling speed, never the reset detector's confirmation rules. */
final class AdaptivePolling {
    static final int NORMAL_MS = 300, FAST_MS = 150, SIGNAL_MS = 900;
    static final long WISH_COST = 100;
    private boolean fast, rewardVisible;
    private int rewardHits, rewardTriggers, balanceTriggers;
    private long lastReward, lastBalanceAt, balance = -1, pendingFrom = -1, pendingValue;
    private String reason = "нет";

    synchronized int intervalMs() { return fast ? FAST_MS : NORMAL_MS; }
    synchronized boolean fast() { return fast; }
    synchronized String reason() { return reason; }
    synchronized int rewardTriggers() { return rewardTriggers; }
    synchronized int balanceTriggers() { return balanceTriggers; }

    synchronized void reward(boolean visible, long now) {
        if (!visible) { rewardHits = 0; rewardVisible = false; return; }
        if (rewardVisible) return;
        rewardHits = lastReward > 0 && now-lastReward <= 1200 ? rewardHits+1 : 1;
        lastReward = now;
        if (rewardHits >= 2) {
            rewardVisible = true; rewardTriggers++; fast = true; reason = "уведомление о награде";
        }
    }

    synchronized void balance(Long value, long now) {
        if (value == null || value < 0 || value > 999999999) return;
        if (balance < 0 || now-lastBalanceAt > 4000) {
            balance = value; lastBalanceAt = now; pendingFrom = -1; return;
        }
        // Require a second reading compatible with the original spending candidate.
        if (pendingFrom >= 0 && value <= pendingValue && isWishDrop(pendingFrom-value)) {
            fast = true; reason = "расход самоцветов на желания"; balanceTriggers++; pendingFrom = -1;
        } else {
            pendingFrom = isWishDrop(balance-value) ? balance : -1;
            pendingValue = value;
        }
        balance = value; lastBalanceAt = now;
    }
    private boolean isWishDrop(long drop) { return drop >= WISH_COST && drop <= WISH_COST*100 && drop % WISH_COST == 0; }

    synchronized void confirmedReset() {
        fast = false; reason = "нет"; pendingFrom = -1;
        balance = -1; lastBalanceAt = 0;
        // A reward already on screen must disappear before it can trigger again.
    }
    synchronized void restartSession() {
        confirmedReset(); rewardVisible = false; rewardHits = 0; lastReward = 0;
        balance = -1; lastBalanceAt = 0;
    }
}
