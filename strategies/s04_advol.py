"""
S4 - Adaptive Volatility-Regime Trend (AVT)

From the AdaptiveTrend literature (arXiv 2602.11708): trend-follow on a mid
horizon, but make the trailing stop a function of the *current volatility
regime* rather than a fixed ATR multiple, and stand aside when the market is
not trending (efficiency ratio / ADX gate). Position size is inverse-volatility
scaled so that risk per trade is constant across regimes.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel
from research.runner import evaluate, line

def arrays(f, dc_n=20, adx_min=20, er_min=0.30, trail_mult=3.0, stop_mult=2.5,
           vol_adapt=True, allow_short=True):
    c = f.close.to_numpy(); a = f.atr14.to_numpy()
    hi = pd.Series(f.close).rolling(dc_n).max().shift(1).to_numpy()
    lo = pd.Series(f.close).rolling(dc_n).min().shift(1).to_numpy()
    gate = (f.adx.to_numpy() > adx_min) & (f.ef.to_numpy() > er_min)
    lng = (c > hi) & gate
    sht = (c < lo) & gate & allow_short
    e = np.where(lng, 1.0, np.where(sht, -1.0, 0.0))
    # widen the trail in high-vol regimes, tighten it in quiet ones
    vr = f.vol_rank.to_numpy()
    k = trail_mult * (0.7 + 0.9 * np.nan_to_num(vr, nan=0.5)) if vol_adapt else trail_mult
    return dict(entry=np.nan_to_num(e), stop=stop_mult * a, tp=np.full(len(f), np.nan),
                trail=k * a, exit=np.zeros(len(f)))

if __name__ == "__main__":
    for tf in ("4h", "12h", "1D"):
        fut, f = panel(tf)
        print(f"\n===== S4 AVT {tf} =====")
        for dc in (20, 40):
            for adxm, erm in ((0, 0.0), (20, 0.30), (25, 0.40)):
                for va in (True, False):
                    a = arrays(f, dc_n=dc, adx_min=adxm, er_min=erm, vol_adapt=va)
                    r = evaluate("x", f, a, tf, verbose=False, risk=0.01, max_lev=5.0,
                                 trail_after_r=1.0)
                    print("  " + line(f"dc{dc} adx{adxm} er{erm} va{int(va)} [ALL]", r["ALL"]) +
                          f" | OOS CAGR{r['OOS']['cagr']*100:7.1f}% PF{r['OOS']['profit_factor']:5.2f}")
