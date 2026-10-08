package to.casorin.fountain;

import java.net.URLEncoder;
import java.io.UnsupportedEncodingException;

public final class SupportForm {
    public static final String URL = "https://docs.google.com/forms/d/e/1FAIpQLSdfClVJYzvOiGtz-HjWTOWb7dDK1CEB1wtrwpe1kKWGA-hW2w/viewform";
    public static final String FIELD = "entry.1882575839";
    private SupportForm() {}

    public static String prefilledUrl(String report) {
        try {
            return URL + "?usp=pp_url&" + FIELD + "=" + URLEncoder.encode(report, "UTF-8");
        } catch (UnsupportedEncodingException impossible) {
            throw new AssertionError(impossible);
        }
    }
}
