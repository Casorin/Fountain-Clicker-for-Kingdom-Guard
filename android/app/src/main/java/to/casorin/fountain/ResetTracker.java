package to.casorin.fountain;

/** Pure observation logic: no Android APIs and no input commands. */
public final class ResetTracker {
    public record Event(long observedAt, long previousFund, Long intervalMs) {}
    public long current;
    public long lastReset;
    private long peak;
    private long baseline;
    private long lastFrame;
    private long lastReadable;
    private long candidateAt;
    private long candidateValue;
    private int candidateHits;
    private boolean armed = true;
    private long highCandidate;

    public Event observe(Long value, long frameTime, long wallTime) {
        if (frameTime <= lastFrame) return null;
        lastFrame = frameTime;
        if (value == null || value < 1000 || value > 9999999) {
            candidateHits = 0;
            return null;
        }
        if (lastReadable != 0 && frameTime - lastReadable > 15000) {
            // The app cannot infer missed resets across a long visibility gap.
            peak = value;
            candidateHits = 0;
            armed = true;
            lastReset = 0;
        }
        lastReadable = frameTime;
        if (peak > 0 && value > peak + 40000) {
            if (Math.abs(value - highCandidate) > 4000) {
                highCandidate = value;
                return null;
            }
        }
        highCandidate = 0;
        current = value;
        if (!armed) {
            if (value >= baseline + Math.max(2000, baseline / 4)) armed = true;
            peak = Math.max(peak, value);
            return null;
        }
        boolean drop = peak >= 10000 && peak - value >= 5000 && value <= peak * .65;
        if (!drop) {
            candidateHits = 0;
            peak = Math.max(peak, value);
            return null;
        }
        if (candidateHits == 0 || value > candidateValue + 4000) {
            candidateAt = wallTime;
            candidateValue = value;
            candidateHits = 1;
            return null;
        }
        candidateHits++;
        if (candidateHits < 3) return null;
        Long interval = lastReset > 0 && candidateAt > lastReset ? candidateAt - lastReset : null;
        Event event = new Event(candidateAt, peak, interval);
        lastReset = candidateAt;
        baseline = value;
        peak = value;
        armed = false;
        candidateHits = 0;
        return event;
    }

    public void restartSession() {
        peak = baseline = current = lastFrame = lastReadable = highCandidate = 0;
        candidateHits = 0;
        armed = true;
        // Do not use the previous session to compute an interval across a gap.
        lastReset = 0;
    }
}
