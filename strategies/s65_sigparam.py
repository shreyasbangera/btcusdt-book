"""
S65 - The parameters nobody swept: how the signals themselves are built.

Stops, targets, holds, thresholds, exponents and weights have all been swept.
The SIGNAL CONSTRUCTIONS never were. They were set once, early, and carried
through every version of the book:

    s_flow    ofi6_res, z-scored over 480 bars   (480 = 240 days)
    s_cmpx    log(cm/perp) differenced 6 bars, z over 120
    s_btcdom  stored z-score of turnover share
    s_fundz   stored z-score of funding
    s_posn    the S7 composite, unchanged

Each of those windows is a free parameter that has never been examined, and
there are more of them than there are execution parameters. Sweeping them
directly on the full sample would be the purest overfitting in the study, so
every choice here is made by WALK-FORWARD: on each 18-month training window the
construction is chosen by in-window Sharpe alone and applied to the next quarter.
The result is compared against the published constructions run identically.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs
import strategies.s45_single as S
import strategies.s46_net as S46
import strategies.s38_orth as s38

LOOK, RESELECT = 18, 3
# (flow z-window, cmpx diff, cmpx z-window, other z-window)
CONS = [(480, 6, 120), (240, 6, 120), (720, 6, 120),
        (480, 3, 120), (480, 12, 120), (480, 6, 60), (480, 6, 240)]
EXPS = (1.0, 2.0, 2.5, 3.0)

_B = {}
def bank():
    """Precompute every construction's unit series once."""
    if _B: return _B
    g = S.grid(S.FULL_START)
    xf = s38.xpanel("12h")
    g = g.merge(xf[["dt", "cm_px"]], on="dt", how="left", suffixes=("", "_x"))
    cm = g["cm_px"] if "cm_px" in g else g["cm_px_x"]
    lg = np.log(cm.to_numpy(float) / g.close.to_numpy(float))
    ofi = g.ofi6_res.to_numpy(float)
    for (fw, cd, cw) in CONS:
        gg = g.copy()
        gg["s_flow"] = zs(ofi, fw)
        gg["s_cmpx"] = zs(pd.Series(lg).diff(cd).to_numpy(), cw)
        U = np.column_stack([S.unit(gg, n) for n in S46.LONG])
        _B[(fw, cd, cw)] = U
    _B["g"] = g
    return _B

def netv(U, exp, cap=3.0):
    v = U @ (np.ones(U.shape[1]) / U.shape[1])
    nz = np.abs(v) > 0
    if nz.sum() < 50: return v
    u = np.sign(v) * np.abs(v) ** exp
    u = u * (np.abs(v[nz]).mean() / max(np.abs(u[nz]).mean(), 1e-12))
    return np.sign(u) * np.minimum(np.abs(u), cap)

def sim(con, exp, start, end, risk, hold=14, stp=3.0, rr=2.0):
    B = bank(); g = B["g"]; u = netv(B[con], exp); a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(u), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(u)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def plan(ref=0.08, fixed_con=None, verbose=False):
    t0 = pd.Timestamp(S.FULL_START, tz="UTC")
    t = t0 + pd.DateOffset(months=LOOK); end = pd.Timestamp(OOS_END, tz="UTC")
    out = []
    while t < end:
        te = min(t + pd.DateOffset(months=RESELECT), end)
        tr0 = t - pd.DateOffset(months=LOOK)
        best = None
        cons = [fixed_con] if fixed_con else CONS
        for con in cons:
            for exp in EXPS:
                m = sim(con, exp, str(tr0.date()), str(t.date()), ref)
                if m["trades"] < 25: continue
                if best is None or m["sharpe"] > best[0]: best = (m["sharpe"], con, exp)
        if best is None: best = (0, fixed_con or CONS[0], 1.0)
        out.append((str(t.date()), str(te.date()), best[1], best[2]))
        if verbose: print(f"    {str(t.date())[:7]}  con {best[1]}  exp {best[2]}")
        t = te
    return out

def replay(p, risk):
    return pd.concat([daily(sim(c, e, s, en, risk)) for s, en, c, e in p])

def stats(r, tag, risk):
    e = np.cumprod(1.0 + r.to_numpy()); yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((e / np.maximum.accumulate(e) - 1).min()); cagr = e[-1] ** (1 / yrs) - 1
    b = bootstrap_dd(r.to_numpy(), n=2500)
    print(f"{tag:>30}{risk*100:5.0f}% | CAGR {cagr*100:7.1f}%  DD {dd*100:6.1f}%  "
          f"Sharpe {r.mean()/r.std()*np.sqrt(365.25):5.2f}  Calmar {cagr/abs(dd):5.2f} | "
          f"boot med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")

if __name__ == "__main__":
    bank()
    print(f"{len(CONS)} signal constructions x {len(EXPS)} exponents, "
          f"walk-forward every {RESELECT} months on the trailing {LOOK}\n")
    pv = plan(verbose=True)
    pf = plan(fixed_con=(480, 6, 120))
    print()
    for risk in (0.06, 0.08, 0.10):
        stats(replay(pv, risk), "construction ALSO searched", risk)
    print()
    for risk in (0.06, 0.08, 0.10):
        stats(replay(pf, risk), "published construction", risk)
    from collections import Counter
    print("\nconstructions chosen:", Counter(str(p[2]) for p in pv).most_common())
