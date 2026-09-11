"""
S14 - Volatility-Squeeze Expansion (VSE)

Volatility is strongly autocorrelated and mean-reverting in level: unusually
compressed ranges are followed by expansion. The trade is not directional until
the break happens - we wait for Bollinger bandwidth to sit in the bottom decile
of its trailing distribution, then take the first decisive close outside the
band, in the direction of the break.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel
from research.runner import evaluate, line
from engine.indicators import bbands, keltner

def arrays(f, bw_pct=0.20, atr_stop=1.5, rr=2.5, confirm=1.0, trend_align=False):
    c = f.close.to_numpy(); a = f.atr14.to_numpy()
    m, u, lo, bw = bbands(c, 20, 2.0)
    bwr = f.bw_rank.to_numpy()
    squeezed = pd.Series(bwr).shift(1).to_numpy() < bw_pct     # compressed BEFORE the break
    up = c > (u + (confirm - 1.0) * a)
    dn = c < (lo - (confirm - 1.0) * a)
    lng = squeezed & up
    sht = squeezed & dn
    if trend_align:
        t = c > f.ema_s.to_numpy()
        lng &= t; sht &= ~t
    e = np.where(lng, 1.0, np.where(sht, -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=atr_stop * a,
                tp=atr_stop * rr * a, exit=np.zeros(len(f)))

if __name__ == "__main__":
    for tf in ("1h", "4h"):
        fut, f = panel(tf)
        print(f"\n===== S14 VSE {tf} =====")
        for bwp in (0.15, 0.30):
            for st, rr in ((1.5, 2.5), (2.0, 2.0), (2.5, 3.0)):
                for ta in (False, True):
                    a = arrays(f, bw_pct=bwp, atr_stop=st, rr=rr, trend_align=ta)
                    r = evaluate("x", f, a, tf, verbose=False, risk=0.015, max_lev=10.0,
                                 max_bars_h=5*24)
                    if r["ALL"]["trades"] < 40: continue
                    print("  " + line(f"bw{bwp} {st}x{rr} trend{int(ta)} [ALL]", r["ALL"]) +
                          f" | OOS CAGR{r['OOS']['cagr']*100:7.1f}% PF{r['OOS']['profit_factor']:5.2f} N{r['OOS']['trades']:4d}")
