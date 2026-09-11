"""
S67 - Short-side asymmetry, chosen by walk-forward rather than by eye.

Both sides of the book earn their place - long-only reaches Sharpe 1.80 and
short-only 1.22, and together they make 2.16, so there is no long-only
shortcut on an asset that tripled over the window. But they are not the same
trade. BTC trends up; a short that goes wrong goes wrong fast, because the
thing that kills shorts is a squeeze, not a drift. So the two sides plausibly
want different risk settings, and the book has always given them identical ones.

Direct testing suggested a tighter stop on shorts is worth a lot (Calmar 4.07 ->
4.40 with CAGR 63.5% -> 77.2%). That is exactly the kind of after-the-fact pick
this study keeps warning about, so it is not adopted here - it is added to the
walk-forward grid and has to earn its place quarter by quarter, against the
symmetric settings, on training data only.

Grid: conviction exponent x short-stop multiplier x short-size multiplier.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

LOOK, RESELECT = 18, 3
EXPS = (1.0, 2.0, 2.5, 3.0)
SSTOP = (1.0, 0.67)        # short stop as a multiple of the long stop
SSIZE = (1.0, 0.75)        # short size as a multiple of the long size

_C = {}
def ctx():
    if not _C:
        g = S.grid(S.FULL_START)
        v = S.composite(g, S46.LONG)
        nz = np.abs(v) > 0
        _C.update(g=g, v=v, bm=float(np.abs(v[nz]).mean()), a=g.atr14.to_numpy(float))
    return _C

def entry(exp, ssize, cap=3.0):
    c = ctx(); v = c["v"]; nz = np.abs(v) > 0
    u = np.sign(v) * np.abs(v) ** exp
    u = u * (c["bm"] / max(np.abs(u[nz]).mean(), 1e-12))
    u = np.sign(u) * np.minimum(np.abs(u), cap)
    return np.where(u < 0, u * ssize, u)

def sim(exp, sstop, ssize, start, end, risk, stp=3.0, rr=2.0, hold=21):
    c = ctx(); g, a = c["g"], c["a"]
    e = entry(exp, ssize)
    mult = np.where(e < 0, stp * sstop, stp)
    arr = dict(entry=np.nan_to_num(e), stop=mult * a, tp=mult * rr * a,
               exit=(np.abs(np.nan_to_num(e)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def plan(ref=0.08, grid=None, verbose=False):
    G = grid or [(e, ss, sz) for e in EXPS for ss in SSTOP for sz in SSIZE]
    t0 = pd.Timestamp(S.FULL_START, tz="UTC")
    t = t0 + pd.DateOffset(months=LOOK); end = pd.Timestamp(OOS_END, tz="UTC")
    out = []
    while t < end:
        te = min(t + pd.DateOffset(months=RESELECT), end)
        tr0 = t - pd.DateOffset(months=LOOK)
        best = None
        for cfg in G:
            m = sim(*cfg, str(tr0.date()), str(t.date()), ref)
            if m["trades"] < 25: continue
            if best is None or m["sharpe"] > best[0]: best = (m["sharpe"], cfg)
        cfg = best[1] if best else G[0]
        out.append((str(t.date()), str(te.date()), cfg))
        if verbose: print(f"    {str(t.date())[:7]}  exp {cfg[0]}  short-stop x{cfg[1]}  short-size x{cfg[2]}")
        t = te
    return out

def replay(p, risk):
    return pd.concat([daily(sim(*cfg, s, e, risk)) for s, e, cfg in p])

def stats(r, tag, risk):
    e = np.cumprod(1.0 + r.to_numpy()); yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((e / np.maximum.accumulate(e) - 1).min()); cagr = e[-1] ** (1 / yrs) - 1
    b = bootstrap_dd(r.to_numpy(), n=3000)
    ys = {}; es = pd.Series(e, index=r.index); pv = 1.0
    for y, gg in es.groupby(es.index.year): ys[int(y)] = float(gg.iloc[-1] / pv - 1); pv = gg.iloc[-1]
    print(f"{tag:>28}{risk*100:5.0f}% | CAGR {cagr*100:7.1f}%  DD {dd*100:6.1f}%  "
          f"Sharpe {r.mean()/r.std()*np.sqrt(365.25):5.2f}  Calmar {cagr/abs(dd):5.2f} | "
          f"boot med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")
    print("        yearly " + " ".join(f"{y}:{x*100:+.0f}%" for y, x in ys.items()))

if __name__ == "__main__":
    print(f"{len(EXPS)*len(SSTOP)*len(SSIZE)} configurations, re-chosen every {RESELECT} months\n")
    pa = plan(verbose=True)
    ps = plan(grid=[(e, 1.0, 1.0) for e in EXPS])      # symmetric control
    print()
    for risk in (0.06, 0.08, 0.10, 0.12):
        stats(replay(pa, risk), "ASYMMETRIC searched", risk)
    print()
    for risk in (0.08, 0.10, 0.12):
        stats(replay(ps, risk), "SYMMETRIC control", risk)
    from collections import Counter
    print("\nchosen:", Counter(str(p[2]) for p in pa).most_common())
