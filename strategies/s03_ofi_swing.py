"""
S3 - Orthogonal Order-Flow Swing (OFS)

Direct exploitation of the single strongest signal found in the screen:
sustained spot taker-buy pressure that is NOT explained by recent price action.
Decile analysis (in-sample): top decile of `ofi96_res` earned +336 bps over the
following 168h vs +82 bps unconditional. Long-biased by construction - the
bottom decile does NOT predict negative returns, so shorts are optional and
gated on a separate trend filter.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel
from research.runner import evaluate, zs, line

def arrays(f, thr=1.0, atr_stop=3.0, rr=2.5, use_short=False, short_thr=1.5,
           trend_filter=True, flow="ofi96_resz"):
    a = f.atr14.to_numpy()
    fl = f[flow].to_numpy()
    up = (f.close.to_numpy() > f.ema_s.to_numpy())
    lng = fl > thr
    if trend_filter:
        lng = lng & up
    sht = (fl < -short_thr) & (~up) if use_short else np.zeros(len(f), bool)
    e = np.where(lng, 1.0, np.where(sht, -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=atr_stop * a,
                tp=atr_stop * rr * a, exit=np.zeros(len(f)))

if __name__ == "__main__":
    for tf in ("4h", "12h"):
        fut, f = panel(tf)
        print(f"\n===== S3 OFS {tf} =====")
        for flow in ("ofi24_resz", "ofi96_resz"):
            for thr in (0.75, 1.25):
                for hold_d, st, rr in ((5, 3.0, 2.0), (10, 3.5, 2.5)):
                    for tfil in (True, False):
                        a = arrays(f, thr=thr, atr_stop=st, rr=rr, trend_filter=tfil, flow=flow)
                        r = evaluate("x", f, a, tf, verbose=False, risk=0.01,
                                     max_lev=5.0, max_bars_h=hold_d * 24)
                        print("  " + line(f"{flow[:6]} thr{thr} {hold_d}d trend{int(tfil)} [ALL]", r["ALL"]) +
                              f" | OOS CAGR{r['OOS']['cagr']*100:7.1f}% PF{r['OOS']['profit_factor']:5.2f}")
