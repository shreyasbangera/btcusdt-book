"""
S7 - Smart-Money vs Retail Positioning Divergence (SMRD)

Binance publishes, every 5 minutes, (a) the long/short ACCOUNT ratio of the top
traders by margin balance, (b) their long/short POSITION ratio, (c) the
long/short account ratio of all accounts (retail), and (d) open interest.

Screen result (IS 2021-01 .. 2024-06, 1h bars):
    tt_vs_retail = z(log(top-trader position ratio / retail account ratio))
        IC +0.108 at h=96  - the strongest single feature found in this study
    retail_acct_z   IC -0.064 at h=48  (fade the crowd)
    tt_acct_z       IC -0.102 at h=96  (a crowded *count* of top accounts is
                                        bearish even when their size is not)

The trade is therefore: side with top-trader POSITIONING, against retail
account positioning, and against a crowded top-trader account count.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel
from research.runner import evaluate, zs, line

def composite(f, w=(1.0, 1.0, 1.0)):
    parts = np.column_stack([
        np.clip(f.tt_vs_retail.to_numpy(), -3, 3) * w[0],
        -np.clip(f.retail_acct_z.to_numpy(), -3, 3) * w[1],
        -np.clip(f.tt_acct_z.to_numpy(), -3, 3) * w[2]])
    return np.nansum(parts, axis=1) / np.sum(w)

def arrays(f, comp, thr=0.7, sthr=None, atr_stop=3.0, rr=2.0, long_only=False):
    a = f.atr14.to_numpy()
    st = thr if sthr is None else sthr
    e = np.where(comp > thr, 1.0, 0.0) if long_only else \
        np.where(comp > thr, 1.0, np.where(comp < -st, -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=atr_stop * a,
                tp=atr_stop * rr * a, exit=np.zeros(len(f)))

if __name__ == "__main__":
    for tf in ("4h", "12h"):
        fut, f = panel(tf)
        f = f[f.dt >= "2021-01-03"].reset_index(drop=True)
        comp = composite(f)
        print(f"\n===== S7 SMRD {tf} =====")
        for thr in (0.4, 0.7, 1.0):
            for hold_d, st, rr in ((3, 2.5, 2.0), (5, 3.0, 2.0), (10, 3.5, 2.5)):
                for lo in (False, True):
                    a = arrays(f, comp, thr=thr, atr_stop=st, rr=rr, long_only=lo)
                    r = evaluate("x", f, a, tf, verbose=False, risk=0.01, max_lev=5.0,
                                 max_bars_h=hold_d * 24, since="2021-01-03")
                    print("  " + line(f"thr{thr} {hold_d}d {st}x{rr} L{int(lo)} [ALL]", r["ALL"]) +
                          f" | OOS CAGR{r['OOS']['cagr']*100:7.1f}% PF{r['OOS']['profit_factor']:5.2f} N{r['OOS']['trades']:4d}")
