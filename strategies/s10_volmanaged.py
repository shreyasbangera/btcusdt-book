"""
S10 - Volatility-Managed Trend Exposure (VMT)

Moreira & Muir showed that scaling exposure by the INVERSE of recent realised
variance raises the Sharpe of almost any risk premium, because volatility is
far more forecastable than returns. Applied to BTC: hold a long (or long/short)
position whose size is target_vol / realised_vol, gated by a slow trend filter,
rebalanced on the decision bar.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, IS_START, IS_END, OOS_END
from engine.weights import simulate
from engine.data import agg, load

def weights(f, target_vol=0.60, vol_n=96, trend_n=200, mode="long_flat",
            max_w=5.0, bar_h=4.0):
    c = f.close.to_numpy()
    lr = pd.Series(np.log(c)).diff()
    bars_yr = 365.25 * 24 / bar_h
    rv = lr.rolling(vol_n).std(ddof=0).to_numpy() * np.sqrt(bars_yr)
    trend = np.sign(c - pd.Series(c).ewm(span=trend_n, adjust=False).mean().to_numpy())
    base = np.divide(target_vol, rv, out=np.zeros_like(rv), where=np.isfinite(rv) & (rv > 0))
    if mode == "long_flat":
        sgn = (trend > 0).astype(float)
    elif mode == "long_short":
        sgn = trend
    else:
        sgn = np.ones_like(trend)
    return np.clip(np.nan_to_num(base * sgn), -max_w, max_w)

def slice_df(f, fut, s, e):
    m = (fut.dt >= s) & (fut.dt < e)
    return fut[m].reset_index(drop=True), m.to_numpy()

if __name__ == "__main__":
    print(f"{'variant':<46}{'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>5}{'Shp':>6}{'Clm':>7}{'gross':>7}")
    for tf, bh in (("4h", 4.0), ("1D", 24.0)):
        fut, f = panel(tf)
        for mode in ("always", "long_flat", "long_short"):
            for tv in (0.4, 0.6, 0.8):
                for vn in (48, 96, 240):
                    w = weights(f, target_vol=tv, vol_n=vn, mode=mode, bar_h=bh)
                    out = {}
                    for lab, s, e in (("IS", IS_START, IS_END), ("OOS", IS_END, OOS_END), ("ALL", IS_START, OOS_END)):
                        sub, m = slice_df(f, fut, s, e)
                        out[lab] = simulate(sub, w[m], max_w=5.0)
                    a = out["ALL"]
                    print(f"{tf} {mode:<11} tv{tv} vn{vn:<4}{'':<8}{a['cagr']*100:7.1f}%{a['max_dd']*100:7.1f}%"
                          f"{a['profit_factor']:6.2f}{a['trades']:5d}{a['sharpe']:6.2f}{a['calmar']:7.2f}{a['avg_gross']:7.2f}"
                          f"  | OOS {out['OOS']['cagr']*100:6.1f}% DD{out['OOS']['max_dd']*100:6.1f}%")
