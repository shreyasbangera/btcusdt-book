"""
S73 - Size to forecast trendiness.

S72 found the thing that actually drives this book's return, and it is not the
signals: it is how TRENDING the market is.  Correlation between 12-month market
trendiness and the book's CAGR over that window is +0.61; between mean signal IC
and Sharpe, +0.66.  Volatility is NEGATIVELY related (-0.26), which is exactly
why the volatility targeting in S34 was Calmar-neutral - it was scaling by the
wrong variable.

The consequence is large.  Over the whole period, sized to the drawdown limit,
the book makes ~136%.  In its best 12-month window it made 152% at 8% risk with
only a 7.5% drawdown, which sized to the same limit is ~408%.  All of that gap
is regime.

So: can trendiness be forecast well enough to size against it?  It only needs to
be persistent, not predictable in any deep sense.

    trend_t = |sum of log returns| / sum of |log returns|   over a trailing window
              (Kaufman's efficiency ratio: 1.0 = a straight line, 0 = pure chop)

    risk_t  = base x clip(trend_t / trend_median, lo, hi)

computed from strictly past bars and applied forward.  Tested against a flat
risk control at matched bootstrap drawdown, which is the only fair comparison.
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

def persistence():
    g = S.grid(S.FULL_START)
    c = g.close.to_numpy(float)
    lr = np.r_[0.0, np.diff(np.log(c))]
    print("Is trendiness persistent?  (12h bars; 60 bars = 30 days)\n")
    print(f"{'lookback':>10}{'horizon':>9}{'corr(now, next)':>18}")
    for n in (60, 120, 180, 360):
        er = eff_ratio(lr, n)
        for h in (60, 120, 180):
            x = er[:-h]; y = er[h:]
            ok = np.isfinite(x) & np.isfinite(y)
            print(f"{n//2:>8}d{h//2:>8}d{np.corrcoef(x[ok], y[ok])[0,1]:>18.3f}")
    return g, lr

def run(g, ent, risk_series, stp=3.0, rr=2.0, hold=21, base=0.08):
    """The engine takes one risk number, so trendiness scaling is folded into
    the entry magnitude instead - mathematically identical, since position size
    is linear in both."""
    a = g.atr14.to_numpy(float)
    e = np.nan_to_num(ent) * np.nan_to_num(risk_series, nan=1.0)
    arr = dict(entry=e, stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(ent)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=S.FULL_START, end=OOS_END, risk=base,
                    max_lev=10.0, max_bars_h=hold * 24)

def stats(m, tag, risk):
    r = pd.Series(m["equity"], index=pd.to_datetime(m["dt"])).resample("1D").last(
        ).dropna().pct_change().fillna(0).to_numpy()
    b = bootstrap_dd(r, n=2500)
    print(f"{tag:>34}{risk*100:5.1f}% | CAGR {m['cagr']*100:7.1f}%  DD {m['max_dd']*100:6.1f}%  "
          f"PF {m['profit_factor']:5.2f}  N {m['trades']:4d}  Shp {m['sharpe']:5.2f}  "
          f"Clm {m['calmar']:5.2f} | med {b['dd_median']*100:6.1f}%  "
          f"P>20% {b['p_dd_worse_than_20']*100:3.0f}%")

if __name__ == "__main__":
    g, lr = persistence()
    v = S.composite(g, S46.LONG)
    nz = np.abs(v) > 0; bm = np.abs(v[nz]).mean()
    u = np.sign(v) * np.abs(v) ** 2.5
    u = np.sign(u) * np.minimum(np.abs(u) * (bm / np.abs(u[nz]).mean()), 3.0)
    print("\n\nSizing to trailing trendiness (exponent 2.5 book)\n")
    print(f"{'variant':>34}{'risk':>6} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'Shp':>6}{'Clm':>6}"
          f" | {'medDD':>7}{'P>20%':>5}")
    for risk in (0.06, 0.08, 0.10):
        stats(run(g, u, np.ones(len(g)), base=risk), "flat risk (control)", risk)
    print()
    for n in (120, 180, 360):
        er = eff_ratio(lr, n)
        med = pd.Series(er).expanding(min_periods=200).median().to_numpy()   # causal
        for lo, hi in ((0.5, 2.0), (0.4, 2.5)):
            sc = np.clip(er / np.maximum(med, 1e-9), lo, hi)
            for risk in (0.06, 0.08):
                stats(run(g, u, sc, base=risk), f"trend-scaled {n//2}d [{lo},{hi}]", risk)
