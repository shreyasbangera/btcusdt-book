"""
S51 - Walk-forward validation of the final book.

A single in-sample/out-of-sample split tests one decision boundary. It does not
test the process that made the choices, and by this point the study has made a
lot of them: the thresholds, the stop multiple, the reward-to-risk ratio, the
holding cap. Several were fixed early and carried forward, which means the
whole sample influenced them.

This re-runs the whole selection honestly. The 5.5 years are cut into rolling
folds. On each TRAIN window a small grid is searched and the best configuration
picked by in-window Sharpe alone; that configuration is then applied, untouched,
to the TEST window immediately after it. The test windows are concatenated into
one equity curve. Nothing in a test window ever informs its own parameters.

Two controls run alongside:
  FIXED     the published configuration applied everywhere, never re-selected
  RANDOM    a configuration drawn at random from the same grid on each fold,
            which is what the walk-forward would score if the grid search had
            no skill at all
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

GRID = [(ts, stp, rr, hold)
        for ts in (0.8, 1.0, 1.3)
        for stp in (2.5, 3.0, 4.0)
        for rr in (1.5, 2.0, 3.0)
        for hold in (14, 21)]

def one(g, names, ts, stp, rr, hold, start, end, risk=0.08):
    U = []
    for n in names:
        z = g[f"s_{n}"].to_numpy(float); t = S.THR[n] * ts
        e = np.where(z > t, 1.0, np.where(z < -t, -1.0, 0.0))
        U.append(np.nan_to_num(e * np.clip(np.abs(z) / t, 1.0, S.CAP)))
    net = np.column_stack(U) @ (np.ones(len(U)) / len(U))
    a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(net), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(net)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def stats(r, label):
    e = np.cumprod(1.0 + r.to_numpy()); idx = r.index
    yrs = (idx[-1] - idx[0]).days / 365.25
    dd = (e / np.maximum.accumulate(e) - 1.0).min()
    cagr = e[-1] ** (1 / yrs) - 1
    sd = r.std()
    b = bootstrap_dd(r.to_numpy(), n=2500)
    print(f"{label:>34} | CAGR {cagr*100:7.1f}%  DD {dd*100:6.1f}%  "
          f"Sharpe {r.mean()/sd*np.sqrt(365.25):5.2f}  Calmar {cagr/abs(dd):5.2f}  "
          f"| boot med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")
    return cagr, dd

if __name__ == "__main__":
    names = S46.LONG
    g = S.grid(S.FULL_START)
    folds = []
    t = pd.Timestamp("2022-09-01", tz="UTC")           # first test window starts here
    while t < pd.Timestamp(OOS_END, tz="UTC"):
        tr0 = t - pd.DateOffset(months=18)
        te1 = min(t + pd.DateOffset(months=6), pd.Timestamp(OOS_END, tz="UTC"))
        folds.append((tr0, t, te1)); t = te1
    print(f"{len(folds)} folds, 18-month train / 6-month test, rolled forward\n")
    rng = np.random.default_rng(7)
    picked, rets, fixed_r, rand_r = [], [], [], []
    for tr0, tr1, te1 in folds:
        best = None
        for cfg in GRID:
            m = one(g, names, *cfg, str(tr0.date()), str(tr1.date()))
            if m["trades"] < 25: continue
            if best is None or m["sharpe"] > best[0]: best = (m["sharpe"], cfg)
        if best is None: continue
        cfg = best[1]
        te = one(g, names, *cfg, str(tr1.date()), str(te1.date()))
        fx = one(g, names, 1.0, 3.0, 2.0, 21, str(tr1.date()), str(te1.date()))
        rc = GRID[rng.integers(len(GRID))]
        rd = one(g, names, *rc, str(tr1.date()), str(te1.date()))
        picked.append((str(tr1.date())[:7], cfg, te["cagr"], fx["cagr"], te["trades"]))
        rets.append(daily(te)); fixed_r.append(daily(fx)); rand_r.append(daily(rd))
        print(f"  test {str(tr1.date())[:7]} -> {str(te1.date())[:7]}   picked thr x{cfg[0]} "
              f"{cfg[1]}ATR x{cfg[2]}R {cfg[3]}d   walk-fwd {te['cagr']*100:7.1f}%   "
              f"fixed {fx['cagr']*100:7.1f}%   N {te['trades']:3d}")
    print()
    stats(pd.concat(rets), "WALK-FORWARD (re-selected)")
    stats(pd.concat(fixed_r), "FIXED published config")
    stats(pd.concat(rand_r), "RANDOM config per fold")
