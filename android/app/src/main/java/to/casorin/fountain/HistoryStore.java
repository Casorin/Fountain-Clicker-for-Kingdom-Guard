package to.casorin.fountain;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONObject;

public final class HistoryStore {
    final SharedPreferences preferences;
    public HistoryStore(Context context) {
        preferences = context.getSharedPreferences("fountain", Context.MODE_PRIVATE);
    }
    public JSONArray events() {
        try { return new JSONArray(preferences.getString("history", "[]")); }
        catch (Exception ignored) { return new JSONArray(); }
    }
    public void append(ResetTracker.Event event) {
        try {
            JSONArray old = events(), result = new JSONArray();
            JSONObject row = new JSONObject().put("time", event.observedAt())
                .put("fund", event.previousFund()).put("interval", event.intervalMs());
            result.put(row);
            for (int i = 0; i < Math.min(199, old.length()); i++) result.put(old.get(i));
            preferences.edit().putString("history", result.toString()).apply();
        } catch (Exception ignored) {}
    }
    public void clear() { preferences.edit().putString("history", "[]").apply(); }
    public double[] region() {
        return new double[]{preferences.getFloat("left", .17f), preferences.getFloat("top", .286f),
            preferences.getFloat("right", .34f), preferences.getFloat("bottom", .313f)};
    }
    public boolean calibrated() { return preferences.getBoolean("calibrated", false); }
    public void region(double left, double top, double right, double bottom) {
        preferences.edit().putFloat("left", (float)left).putFloat("top", (float)top)
            .putFloat("right", (float)right).putFloat("bottom", (float)bottom)
            .putBoolean("calibrated", true).apply();
    }
    public static String amount(long value) { return String.format(java.util.Locale.US, "%,d", value).replace(',', ' '); }
    public static String duration(long milliseconds) {
        long seconds = Math.max(0, milliseconds / 1000);
        if (seconds >= 3600) return (seconds / 3600) + " ч " + (seconds / 60 % 60) + " мин";
        return (seconds / 60) + " мин " + String.format(java.util.Locale.US, "%02d", seconds % 60) + " сек";
    }
}
