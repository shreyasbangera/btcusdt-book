"""
S60 - The walk-forward turned into the strategy itself.

S59 searched the conviction exponent on each training window and found the
choice is REGIME-DEPENDENT: the early folds want |net|^1 (spread the bet across
whatever agrees), the later ones want |net|^2.5 to ^3 (bet almost only on
unanimity). Neither fixed choice is right for the whole sample, and the
walk-forward beat both because it adapted.

That is not just a validation result - it is implementable. Nothing about
re-choosing the exponent every quarter from the trailing 18 months requires
knowing the future.

    every RESELECT months:
        for each candidate shape and stop/target pair:
            simulate the book over the trailing LOOKBACK months
        adopt whichever had the highest Sharpe over that window
    trade it until the next reselection

The whole series is generated forward: at any date the configuration in force
was chosen only from data strictly before it. The first LOOKBACK months are
spent warming up and are excluded from the reported result.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

LOOKBACK = 18      # months of history the choice is made on
RESELECT = 3       # months between re-choices
GRID = [(p, stp, rr, hold) for p in (1.0, 1.5, 2.0, 2.5, 3.0)
        for stp in (2.5, 3.0) for rr in (2.0, 3.0) for hold in (14, 21)]

_G = {}
def ctx():
    if not _G:
        g = S.grid(S.FULL_START)
        v = S.composite(g, S46.LONG)
        nz = np.abs(v) > 0
        _G.update(g=g, v=v, bm=float(np.abs(v[nz]).mean()), nz=nz)
    return _G

def shape(p, cap=3.0):
    c = ctx(); v, bm, nz = c["v"], c["bm"], c["nz"]
    u = np.sign(v) * np.abs(v) ** p
    u = u * (bm / np.abs(u[nz]).mean())
    return np.sign(u) * np.minimum(np.abs(u), cap)

def sim(p, stp, rr, hold, start, end, risk):
    g = ctx()["g"]; u = shape(p); a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(u), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(u)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def adaptive(risk, verbose=False):
    """Forward-generated: each block's config chosen only from data before it."""
    t0 = pd.Timestamp(S.FULL_START, tz="UTC")
    start = t0 + pd.DateOffset(months=LOOKBACK)
    end = pd.Timestamp(OOS_END, tz="UTC")
    segs, chosen = [], []
    t = start
    while t < end:
        te = min(t + pd.DateOffset(months=RESELECT), end)
        tr0 = t - pd.DateOffset(months=LOOKBACK)
        best = None
        for cfg in GRID:
            m = sim(*cfg, str(tr0.date()), str(t.date()), risk)
            if m["trades"] < 25: continue
            if best is None or m["sharpe"] > best[0]: best = (m["sharpe"], cfg)
        cfg = best[1] if best else (1.0, 3.0, 2.0, 21)
        blk = sim(*cfg, str(t.date()), str(te.date()), risk)
        segs.append(daily(blk)); chosen.append((str(t.date())[:7], cfg, blk["trades"]))
        if verbose:
            print(f"    {str(t.date())[:7]} -> {str(te.date())[:7]}  exponent {cfg[0]} "
                  f"{cfg[1]}ATR x{cfg[2]}R {cfg[3]}d   N {blk['trades']:3d}")
        t = te
    return pd.concat(segs), chosen

def stats(r, tag, risk):
    e = np.cumprod(1.0 + r.to_numpy()); yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((e / np.maximum.accumulate(e) - 1).min())
    cagr = e[-1] ** (1 / yrs) - 1
    b = bootstrap_dd(r.to_numpy(), n=3000)
    ys = {}; es = pd.Series(e, index=r.index); pv = 1.0
    for y, gg in es.groupby(es.index.year): ys[int(y)] = float(gg.iloc[-1] / pv - 1); pv = gg.iloc[-1]
    print(f"{tag:>26}{risk*100:5.0f}% | CAGR {cagr*100:7.1f}%  DD {dd*100:6.1f}%  "
          f"Sharpe {r.mean()/r.std()*np.sqrt(365.25):5.2f}  Calmar {cagr/abs(dd):5.2f} | "
          f"boot med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")
    print("        yearly " + " ".join(f"{y}:{x*100:+.0f}%" for y, x in ys.items()))
    return cagr, dd

if __name__ == "__main__":
    print(f"adaptive exponent: {LOOKBACK}-month lookback, re-chosen every {RESELECT} months, "
          f"{len(GRID)} configurations\n")
    r, chosen = adaptive(0.08, verbose=True)
    print()
    for risk in (0.06, 0.08, 0.10, 0.12, 0.14):
        rr, _ = adaptive(risk)
        stats(rr, "ADAPTIVE exponent", risk)
    print()
    for risk in (0.08, 0.10):
        g = ctx()["g"]
        m = sim(1.0, 3.0, 2.0, 21, str((pd.Timestamp(S.FULL_START, tz="UTC")
                + pd.DateOffset(months=LOOKBACK)).date()), OOS_END, risk)
        stats(daily(m), "FIXED linear (control)", risk)
