"""
S61 - Adaptive weights on top of the adaptive exponent.

Re-choosing the conviction exponent each quarter took Calmar from 4.70 to 6.34.
The signal WEIGHTS have never been adaptive at all: they are equal and fixed
forever. An in-sample-fitted static weighting was tested early and was worse
than equal - but that is a different thing from a rolling one, and the exponent
result is direct evidence that adaptivity beats any fixed choice when the thing
being chosen is regime-dependent.

Every quarter, on the trailing 18 months only, choose jointly:

    exponent   1.0 / 1.5 / 2.0 / 2.5 / 3.0
    weights    EQUAL           all five the same
               IC              proportional to each signal's trailing rank-IC
                               against forward one-day returns, floored at zero
               ICSQ            the same, squared - concentrate harder
               DROP1           equal, minus the single worst signal by trailing IC
    exit       3.0 ATR x 2R  or  2.5 ATR x 3R

Weights come from a numpy correlation on past data, so the search costs one
backtest per configuration rather than one per signal per configuration. The
selection is run once at a reference size and the chosen sequence replayed at
every risk level, since Sharpe is near-invariant to position size.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from research.harness import backtest, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

LOOKBACK, RESELECT = 18, 3
EXPS = (1.0, 1.5, 2.0, 2.5, 3.0)
WMODES = ("EQUAL", "IC", "ICSQ", "DROP1")
EXITS = ((3.0, 2.0), (2.5, 3.0))

_C = {}
def ctx():
    if not _C:
        g = S.grid(S.FULL_START)
        U = np.column_stack([S.unit(g, n) for n in S46.LONG])
        c = g.close.to_numpy(float)
        fwd = np.full(len(c), np.nan); fwd[:-2] = c[2:] / c[:-2] - 1.0   # forward 1 day
        _C.update(g=g, U=U, fwd=fwd, dt=g.dt.to_numpy())
    return _C

def weights(mode, mask):
    """Weights from trailing data only. `mask` selects the lookback window."""
    c = ctx(); U, fwd = c["U"], c["fwd"]
    k = U.shape[1]
    if mode == "EQUAL":
        return np.ones(k) / k
    ic = np.zeros(k)
    for i in range(k):
        x = U[:, i]; g = mask & np.isfinite(x) & np.isfinite(fwd) & (np.abs(x) > 0)
        ic[i] = spearmanr(x[g], fwd[g])[0] if g.sum() > 100 else 0.0
    ic = np.nan_to_num(ic)
    if mode == "DROP1":
        w = np.ones(k); w[int(np.argmin(ic))] = 0.0
        return w / w.sum()
    p = np.clip(ic, 0, None)
    if mode == "ICSQ": p = p ** 2
    return (p / p.sum()) if p.sum() > 1e-9 else np.ones(k) / k

def netvec(w, exp, cap=3.0):
    c = ctx(); v = c["U"] @ w
    nz = np.abs(v) > 0
    if nz.sum() < 50: return v
    bm = np.abs(v[nz]).mean()
    u = np.sign(v) * np.abs(v) ** exp
    u = u * (bm / max(np.abs(u[nz]).mean(), 1e-12))
    return np.sign(u) * np.minimum(np.abs(u), cap)

def sim(w, exp, stp, rr, start, end, risk, hold=14):
    g = ctx()["g"]; u = netvec(w, exp); a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(u), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(u)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def choose(ref_risk=0.08, verbose=False):
    """Forward selection: each block's config comes only from data before it."""
    c = ctx(); dts = pd.to_datetime(c["dt"])
    t0 = pd.Timestamp(S.FULL_START, tz="UTC")
    t = t0 + pd.DateOffset(months=LOOKBACK); end = pd.Timestamp(OOS_END, tz="UTC")
    plan = []
    while t < end:
        te = min(t + pd.DateOffset(months=RESELECT), end)
        tr0 = t - pd.DateOffset(months=LOOKBACK)
        mask = (dts >= tr0) & (dts < t)
        best = None
        for wm in WMODES:
            w = weights(wm, mask)
            for exp in EXPS:
                for stp, rr in EXITS:
                    m = sim(w, exp, stp, rr, str(tr0.date()), str(t.date()), ref_risk)
                    if m["trades"] < 25: continue
                    if best is None or m["sharpe"] > best[0]:
                        best = (m["sharpe"], wm, w, exp, stp, rr)
        if best is None:
            best = (0.0, "EQUAL", np.ones(5) / 5, 1.0, 3.0, 2.0)
        _, wm, w, exp, stp, rr = best
        plan.append((str(t.date()), str(te.date()), wm, w, exp, stp, rr))
        if verbose:
            print(f"    {str(t.date())[:7]} -> {str(te.date())[:7]}  {wm:>5} exp {exp} "
                  f"{stp}x{rr}  w=" + " ".join(f"{x:.2f}" for x in w))
        t = te
    return plan

def replay(plan, risk):
    segs = []
    for s, e, wm, w, exp, stp, rr in plan:
        segs.append(daily(sim(w, exp, stp, rr, s, e, risk)))
    return pd.concat(segs)

def stats(r, tag, risk):
    e = np.cumprod(1.0 + r.to_numpy()); yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((e / np.maximum.accumulate(e) - 1).min()); cagr = e[-1] ** (1 / yrs) - 1
    b = bootstrap_dd(r.to_numpy(), n=3000)
    ys = {}; es = pd.Series(e, index=r.index); pv = 1.0
    for y, gg in es.groupby(es.index.year): ys[int(y)] = float(gg.iloc[-1] / pv - 1); pv = gg.iloc[-1]
    print(f"{tag:>26}{risk*100:5.0f}% | CAGR {cagr*100:7.1f}%  DD {dd*100:6.1f}%  "
          f"Sharpe {r.mean()/r.std()*np.sqrt(365.25):5.2f}  Calmar {cagr/abs(dd):5.2f} | "
          f"boot med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")
    print("        yearly " + " ".join(f"{y}:{x*100:+.0f}%" for y, x in ys.items()))

if __name__ == "__main__":
    print(f"joint selection: {len(WMODES)} weightings x {len(EXPS)} exponents x {len(EXITS)} exits"
          f", re-chosen every {RESELECT} months on the trailing {LOOKBACK}\n")
    plan = choose(verbose=True)
    print()
    for risk in (0.06, 0.08, 0.10, 0.12):
        stats(replay(plan, risk), "ADAPTIVE weights+exp", risk)
    print()
    flat = [(s, e, "EQUAL", np.ones(5) / 5, 1.0, 3.0, 2.0) for s, e, *_ in plan]
    for risk in (0.08, 0.10):
        stats(replay(flat, risk), "FIXED equal, linear", risk)
    from collections import Counter
    print("\nweighting chosen:", Counter(p[2] for p in plan).most_common())
    print("exponent chosen:", Counter(p[4] for p in plan).most_common())
