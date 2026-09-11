"""
S81 - Orthogonalise all five signals, not just one.

`s_flow` is built as taker imbalance projected off past returns over 1/2/4/6/12
and 24 bars, with the coefficients refit monthly on an expanding window of
strictly past data.  That construction is why it works: raw taker imbalance is
contaminated by short-horizon reversal, and removing the part recent price action
already explains is what leaves a signal.

The other four have never had the same treatment.  `s_cmpx`, `s_btcdom`,
`s_fundz` and `s_posn` are plain rolling z-scores.  Each could be carrying
momentum contamination of its own - funding mechanically follows price, crowded
positioning follows price, and turnover share moves with which asset is running.
If so, projecting it out should sharpen them, exactly as it did for flow and for
the implied-volatility signal in S36 (where the residual's IC was HIGHER than the
raw series').

Tested one signal at a time and then all together, so a gain can be attributed.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from research.harness import backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

BPM = 60          # 12h bars per month

def orthogonalise(x, ctrl, warm_months=6):
    """Project x off ctrl, coefficients refit monthly on strictly past data."""
    x = np.asarray(x, float)
    good = np.isfinite(x) & np.isfinite(ctrl).all(1)
    out = np.full(len(x), np.nan); coef = None
    for i0 in range(BPM * warm_months, len(x), BPM):
        hist = good.copy(); hist[i0:] = False
        if hist.sum() > 200:
            A = np.column_stack([np.ones(hist.sum()), ctrl[hist]])
            coef = np.linalg.lstsq(A, x[hist], rcond=None)[0]
        if coef is None: continue
        j1 = min(i0 + BPM, len(x)); sl = slice(i0, j1); gm = good[sl]
        seg = np.full(j1 - i0, np.nan)
        seg[gm] = x[sl][gm] - np.column_stack([np.ones(gm.sum()), ctrl[sl][gm]]) @ coef
        out[sl] = seg
    return out

def rz(x, w=120):
    s = pd.Series(np.asarray(x, float))
    return ((s - s.rolling(w).mean()) / (s.rolling(w).std() + 1e-12)).to_numpy()

def net_of(sigs, exp=2.5, cap=3.0):
    U = []
    for n, z in sigs.items():
        t = S.THR[n]
        e = np.where(z > t, 1.0, np.where(z < -t, -1.0, 0.0))
        U.append(np.nan_to_num(e * np.clip(np.abs(z) / t, 1.0, S.CAP)))
    v = np.column_stack(U) @ (np.ones(len(U)) / len(U))
    nz = np.abs(v) > 0
    if nz.sum() < 50: return v
    u = np.sign(v) * np.abs(v) ** exp
    return np.sign(u) * np.minimum(np.abs(u) * (np.nanmean(np.abs(v[nz])) /
                                   max(np.nanmean(np.abs(u[nz])), 1e-12)), cap)

def go(g, ent, tag, risk=0.08, stp=2.5, rr=3.0, hold=14):
    a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(ent), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(ent)) <= 0.0).astype(float))
    A = backtest(g, arr, "12h", start=S.FULL_START, end=OOS_END, risk=risk,
                 max_lev=10.0, max_bars_h=hold * 24)
    O = backtest(g, arr, "12h", start=IS_END, end=OOS_END, risk=risk,
                 max_lev=10.0, max_bars_h=hold * 24)
    r = pd.Series(A["equity"], index=pd.to_datetime(A["dt"])).resample("1D").last(
        ).dropna().pct_change().fillna(0).to_numpy()
    b = bootstrap_dd(r, n=1500)
    print(f"{tag:>30}{risk*100:5.0f}% | CAGR {A['cagr']*100:7.1f}%  DD {A['max_dd']*100:6.1f}%  "
          f"PF {A['profit_factor']:5.2f}  N {A['trades']:4d}  Shp {A['sharpe']:5.2f}  "
          f"Clm {A['calmar']:5.2f} | OOS {O['cagr']*100:6.1f}%  P>20% "
          f"{b['p_dd_worse_than_20']*100:3.0f}%")

if __name__ == "__main__":
    g = S.grid(S.FULL_START)
    c = g.close.to_numpy(float); lc = np.log(c)
    ctrl = np.column_stack([pd.Series(lc).diff(k).to_numpy() for k in (1, 2, 4, 6, 12, 24)])
    raw = {n: g[f"s_{n}"].to_numpy(float) for n in S46.LONG}
    fwd = np.full(len(c), np.nan); fwd[:-2] = c[2:] / c[:-2] - 1.0
    print("does each signal carry momentum contamination, and does removing it raise its IC?\n")
    print(f"{'signal':>10}{'corr to past ret':>18}{'raw IC':>10}{'resid IC':>10}")
    res = {}
    for n in S46.LONG:
        if n == "flow":
            res[n] = raw[n]; continue
        o = rz(orthogonalise(raw[n], ctrl))
        res[n] = o
        ok = np.isfinite(raw[n]) & np.isfinite(fwd)
        ok2 = np.isfinite(o) & np.isfinite(fwd)
        cc = np.corrcoef(raw[n][np.isfinite(raw[n]) & np.isfinite(ctrl[:, 3])],
                         ctrl[:, 3][np.isfinite(raw[n]) & np.isfinite(ctrl[:, 3])])[0, 1]
        print(f"{n:>10}{cc:>18.3f}{spearmanr(raw[n][ok], fwd[ok])[0]:>10.4f}"
              f"{spearmanr(o[ok2], fwd[ok2])[0]:>10.4f}")
    print(f"\n{'variant':>30}{'risk':>6} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'Shp':>6}{'Clm':>6}"
          f" | {'OOS':>6}{'P>20%':>7}")
    go(g, net_of(raw), "all raw (control)")
    for n in S46.LONG:
        if n == "flow": continue
        mix = dict(raw); mix[n] = res[n]
        go(g, net_of(mix), f"orthogonalised: {n}")
    go(g, net_of(res), "orthogonalised: all four")
