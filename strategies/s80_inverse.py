"""
S80 - If trendiness mean-reverts, size AGAINST it.

S73 scaled risk up with trailing trendiness, on the theory that the book earns
more in trending markets (+0.61) so it should lean into them.  Every variant
lost, and the persistence table said why: trendiness is NEGATIVELY autocorrelated
at the horizons that matter - 60d vs the next 60d is -0.117, 90d vs the next 90d
is -0.211.  Leaning into a trend buys a regime about to end.

That measurement points the other way and the obvious follow-up was not run.
If a trending quarter is followed by a quieter one, then the time to be LARGE is
after chop, not after a trend:

    risk_t = base x clip(median_trend / trend_t, lo, hi)

Same construction as S73 with the ratio inverted, computed from strictly past
bars.  Also tested: the same inversion applied to the CONVICTION exponent rather
than to size, since the exponent is the lever that actually moved this study.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

def eff_ratio(lr, n):
    s = pd.Series(lr)
    return (s.rolling(n).sum().abs() / (s.abs().rolling(n).sum() + 1e-12)).to_numpy()

def base_net(g, exp=2.5, cap=3.0):
    U = [S.unit(g, n) for n in S46.LONG]
    v = np.column_stack(U) @ (np.ones(len(U)) / len(U))
    nz = np.abs(v) > 0
    u = np.sign(v) * np.abs(v) ** exp
    return np.sign(u) * np.minimum(np.abs(u) * (np.abs(v[nz]).mean() /
                                   max(np.abs(u[nz]).mean(), 1e-12)), cap)

def go(g, ent, tag, risk=0.08, stp=2.5, rr=3.0, hold=14):
    a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(ent), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(ent)) <= 0.0).astype(float))
    A = backtest(g, arr, "12h", start=S.FULL_START, end=OOS_END, risk=risk,
                 max_lev=10.0, max_bars_h=hold * 24)
    r = pd.Series(A["equity"], index=pd.to_datetime(A["dt"])).resample("1D").last(
        ).dropna().pct_change().fillna(0).to_numpy()
    b = bootstrap_dd(r, n=1500)
    print(f"{tag:>36}{risk*100:5.0f}% | CAGR {A['cagr']*100:7.1f}%  DD {A['max_dd']*100:6.1f}%  "
          f"PF {A['profit_factor']:5.2f}  N {A['trades']:4d}  Shp {A['sharpe']:5.2f}  "
          f"Clm {A['calmar']:5.2f} | med {b['dd_median']*100:6.1f}%  "
          f"P>20% {b['p_dd_worse_than_20']*100:3.0f}%")

if __name__ == "__main__":
    g = S.grid(S.FULL_START)
    c = g.close.to_numpy(float)
    lr = np.r_[0.0, np.diff(np.log(c))]
    v = base_net(g)
    print(f"{'variant':>36}{'risk':>6} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'Shp':>6}{'Clm':>6}"
          f" | {'medDD':>7}{'P>20%':>6}")
    for risk in (0.06, 0.08, 0.10):
        go(g, v, "flat risk (control)", risk)
    print()
    for n in (120, 180, 360):
        er = eff_ratio(lr, n)
        med = pd.Series(er).expanding(min_periods=200).median().to_numpy()   # causal
        for lo, hi in ((0.6, 1.7), (0.5, 2.0)):
            sc = np.clip(np.where(er > 1e-9, med / er, 1.0), lo, hi)
            for risk in (0.08,):
                go(g, v * sc, f"INVERSE trend size {n//2}d [{lo},{hi}]", risk)
    print()
    # inversion applied to the conviction exponent instead of to size
    for n in (180, 360):
        er = eff_ratio(lr, n)
        med = pd.Series(er).expanding(min_periods=200).median().to_numpy()
        ratio = np.clip(np.where(er > 1e-9, med / er, 1.0), 0.6, 1.7)
        U = [S.unit(g, n_) for n_ in S46.LONG]
        raw = np.column_stack(U) @ (np.ones(len(U)) / len(U))
        nz = np.abs(raw) > 0; bm = np.abs(raw[nz]).mean()
        expv = np.nan_to_num(np.clip(2.5 * ratio, 1.0, 4.0), nan=2.5)
        u = np.sign(raw) * np.abs(raw) ** expv
        # nanmean: a NaN anywhere in u poisons the mean and zeroes every entry
        u = np.sign(u) * np.minimum(np.abs(u) * (bm / max(np.nanmean(np.abs(u[nz])), 1e-12)), 3.0)
        for risk in (0.08,):
            go(g, u, f"INVERSE trend exponent {n//2}d", risk)
