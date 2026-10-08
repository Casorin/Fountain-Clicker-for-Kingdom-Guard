package to.casorin.fountain;

final class WishPixels {
    private WishPixels() {}
    static boolean white(int c) {
        int r=c>>16&255,g=c>>8&255,b=c&255;
        return Math.min(r,Math.min(g,b)) >= 185 && Math.max(r,Math.max(g,b))-Math.min(r,Math.min(g,b)) <= 25;
    }
    private static boolean diamond(int c) {
        int r=c>>16&255,g=c>>8&255,b=c&255;
        return b>=175 && g>=145 && g-r>=30 && b-r>=40;
    }
    static boolean reward(int[] colors,int width,int height,double[] fund) {
        int left=(int)(width*.36),right=(int)(width*.88);
        int top=Math.max(0,(int)(height*(fund[1]-.07))),bottom=Math.min(height,(int)(height*(fund[3]+.12)));
        int groups=0,run=0;
        for(int y=top;y<bottom;y++) {
            int count=0,first=right,last=left;
            for(int x=left;x<right;x++) if(white(colors[y*width+x])) { count++; first=Math.min(first,x); last=x; }
            boolean text=count>=(right-left)*.12 && last-first>=(right-left)*.55;
            if(text) run++;
            else {
                if(run>=2 && run<=width*.08) groups++;
                run=0;
            }
        }
        if(run>=2 && run<=width*.08) groups++;
        return groups>=2;
    }

    /** Locate the cyan currency diamond, then read only the white number to its right. */
    static double[] balanceRegion(int[] colors,int width,int height,double[] fund) {
        int topLimit=Math.min(height,(int)(height*fund[1]*.5));
        boolean[] seen=new boolean[colors.length]; int[] queue=new int[colors.length];
        int best=0,bt=0,br=0,bb=0;
        for(int y=0;y<topLimit;y++) for(int x=(int)(width*.65);x<width*.86;x++) {
            int seed=y*width+x;
            if(seen[seed] || !diamond(colors[seed])) continue;
            int head=0,tail=1,left=x,right=x,top=y,bottom=y; queue[0]=seed; seen[seed]=true;
            while(head<tail) {
                int at=queue[head++],px=at%width,py=at/width;
                left=Math.min(left,px);right=Math.max(right,px);top=Math.min(top,py);bottom=Math.max(bottom,py);
                for(int offset:new int[]{-1,1,-width,width}) {
                    int next=at+offset;
                    if(next<0 || next>=colors.length || Math.abs(next%width-px)+Math.abs(next/width-py)!=1
                        || next/width>=topLimit || next%width<width*.65 || next%width>=width*.86 || seen[next]) continue;
                    seen[next]=true; if(diamond(colors[next])) queue[tail++]=next;
                }
            }
            int w=right-left+1,h=bottom-top+1;
            if(tail>=8 && w>=width*.025 && w<=width*.12 && h>=width*.015 && h<=width*.12 && tail>best) {
                best=tail;bt=top;br=right;bb=bottom;
            }
        }
        if(best==0) return null;
        double left=(br+1.5)/width,right=.915;
        if(right-left<.04) return null;
        double padding=Math.max(1,(bb-bt)*.2);
        return new double[]{left,Math.max(0,(bt-padding)/height),right,Math.min(1,(bb+1+padding)/height)};
    }
    static Long parseBalance(String text) {
        String digits=text.replaceAll("[\\s\\p{Z}]","");
        if(!digits.matches("[0-9]{1,9}")) return null;
        try { return Long.parseLong(digits); } catch(NumberFormatException ignored) { return null; }
    }
}
