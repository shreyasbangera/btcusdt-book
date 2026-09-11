"""
S62 - Continuous exposure instead of discrete trades.

Everything so far enters at full size and holds until a stop, a target, the
flat-exit or the 21-day cap. Exposure is close to binary: the book is either
all-in or out. That is what makes the drawdowns - a position taken at high
conviction is still carried at full size after conviction has decayed, right up
until the stop fires.

A continuous book never has that problem. Each bar it targets an exposure
proportional to current conviction and rebalances toward it, so size decays with
the signal instead of waiting for a price level to be hit. The cost is turnover:
every adjustment pays the 16 bps round turn on the traded increment.

    w[t] = scale x sign(net) x |net|^exp / vol_t     capped at max_w

with vol_t the trailing realised volatility, so the exposure is
volatility-normalised the way the discrete book's ATR stop implicitly was.
w[t] is decided on the closed bar and applied from t+1.

Also tested: a dead band on rebalancing, so small adjustments are skipped and
turnover is not paid on noise.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from engine.weights import simulate
from engine.data import load
from research.harness import IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

def build(exp=2.0, scale=0.30, vol_n=40, max_w=5.0, band=0.0):
    g = S.grid(S.FULL_START)
    v = S.composite(g, S46.LONG)
    nz = np.abs(v) > 0
    u = np.sign(v) * np.abs(v) ** exp
    u = u * (np.abs(v[nz]).mean() / max(np.abs(u[nz]).mean(), 1e-12))
    c = g.close.to_numpy(float)
    lr = np.r_[0.0, np.diff(np.log(c))]
    vol = pd.Series(lr).rolling(vol_n).std().to_numpy() * np.sqrt(730)   # annualised, 12h bars
    w = scale * u / np.maximum(vol, 1e-6)
    w = np.clip(np.nan_to_num(w), -max_w, max_w)
    if band > 0:                       # skip rebalances smaller than `band`
        out = np.zeros_like(w); cur = 0.0
        for i in range(len(w)):
            if abs(w[i] - cur) > band: cur = w[i]
            out[i] = cur
        w = out
    return g, w

def run(g, w, start, end, max_w=5.0):
    m = (g.dt >= start) & (g.dt < end)
    sub = g[m].reset_index(drop=True)
    return simulate(sub, w[m.to_numpy()], max_w=max_w)

def report(tag, g, w, max_w=5.0):
    A = run(g, w, S.FULL_START, OOS_END, max_w)
    I = run(g, w, S.FULL_START, IS_END, max_w)
    O = run(g, w, IS_END, OOS_END, max_w)
    eq = pd.Series(A["equity"], index=pd.to_datetime(g[(g.dt >= S.FULL_START) &
                                                       (g.dt < OOS_END)].dt.to_numpy()))
    r = eq.resample("1D").last().dropna().pct_change().fillna(0).to_numpy()
    b = bootstrap_dd(r, n=2500)
    cs = A["calmar"] / A["sharpe"] if A["sharpe"] > 0 else 0
    print(f"{tag:>32} | {A['cagr']*100:7.1f}%{A['max_dd']*100:7.1f}%{A['profit_factor']:6.2f}"
          f"{A['trades']:6d}{A['sharpe']:6.2f}{A['calmar']:6.2f}{cs:6.2f} | "
          f"{I['cagr']*100:6.1f}%{O['cagr']*100:7.1f}% | {b['dd_median']*100:6.1f}%"
          f"{b['p_dd_worse_than_20']*100:5.0f}%")
    return A

if __name__ == "__main__":
    print(f"{'variant':>32} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'Shp':>6}{'Clm':>6}{'C/S':>6}"
          f" | {'IS':>6}{'OOS':>7} | {'medDD':>7}{'P>20%':>5}")
    for exp in (1.0, 2.0, 2.5):
        for scale in (0.20, 0.30, 0.45):
            g, w = build(exp=exp, scale=scale)
            report(f"cont exp{exp} scale{scale}", g, w)
    print()
    for band in (0.10, 0.25, 0.50):
        g, w = build(exp=2.0, scale=0.30, band=band)
        report(f"cont exp2.0 s0.30 band{band}", g, w)
    print()
    for vn in (20, 80):
        g, w = build(exp=2.0, scale=0.30, vol_n=vn)
        report(f"cont exp2.0 s0.30 vol_n{vn}", g, w)
