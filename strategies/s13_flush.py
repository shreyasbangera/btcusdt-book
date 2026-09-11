"""
S13 - Liquidation-Cascade Reversal (LCR)

A forced-liquidation cascade shows a distinctive joint signature: price falls
hard WHILE open interest collapses (positions are being closed involuntarily,
not opened). That combination marks capitulation rather than informed selling,
and tends to be followed by a sharp snap-back. The reverse - a squeeze of shorts
- is the mirror image.

Signal (closed 1h bars, OI from the Binance 5-min metrics feed):
    long  : 24h return < -r_thr  AND  24h change in open interest < -oi_thr
    short : 24h return > +r_thr  AND  24h change in open interest < -oi_thr
            (a rally on collapsing OI is short-covering, not accumulation)
Rare by construction, so it is sized more aggressively than the other books.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel
from research.runner import evaluate, line

def arrays(f, r_thr=0.05, oi_thr=0.04, lb=24, atr_stop=2.0, rr=2.0,
           allow_short=True, rsi_gate=None):
    c = f.close.to_numpy()
    r = pd.Series(np.log(c)).diff(lb).to_numpy()
    doi = pd.Series(f.oi.to_numpy()).pct_change(lb).to_numpy()
    a = f.atr14.to_numpy()
    lng = (r < -r_thr) & (doi < -oi_thr)
    sht = (r > r_thr) & (doi < -oi_thr) & allow_short
    if rsi_gate is not None:
        lng &= (f.rsi14.to_numpy() < rsi_gate)
        sht &= (f.rsi14.to_numpy() > 100 - rsi_gate)
    e = np.where(lng, 1.0, np.where(sht, -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=atr_stop * a,
                tp=atr_stop * rr * a, exit=np.zeros(len(f)))

if __name__ == "__main__":
    for tf in ("1h", "4h"):
        fut, f = panel(tf)
        f = f[f.dt >= "2021-01-03"].reset_index(drop=True)
        lb = 24 if tf == "1h" else 6
        print(f"\n===== S13 LCR {tf} =====")
        for rt in (0.03, 0.05, 0.07):
            for ot in (0.02, 0.04, 0.06):
                for sh in (True, False):
                    a = arrays(f, r_thr=rt, oi_thr=ot, lb=lb, allow_short=sh)
                    r = evaluate("x", f, a, tf, verbose=False, risk=0.02, max_lev=10.0,
                                 max_bars_h=3*24, since="2021-01-03")
                    if r["ALL"]["trades"] < 40: continue
                    print("  " + line(f"r{rt} oi{ot} short{int(sh)} [ALL]", r["ALL"]) +
                          f" | OOS CAGR{r['OOS']['cagr']*100:7.1f}% PF{r['OOS']['profit_factor']:5.2f} N{r['OOS']['trades']:4d}")
