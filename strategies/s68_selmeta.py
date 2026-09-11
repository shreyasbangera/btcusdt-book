"""
S68 - Interrogating the adaptive layer itself.

Re-choosing the conviction curve quarterly took Calmar from 3.68 to 5.89. But
the RE-SELECTION RULE has never been examined, and it contains three arbitrary
choices made in one sitting:

  OBJECTIVE  it picks the configuration with the best trailing SHARPE.  Sharpe
             is close to size-invariant, so it selects shape and ignores
             drawdown - while the thing being maximised is Calmar.  Selecting
             on Calmar directly is the obvious thing nobody tried.
  LOOKBACK   18 months, chosen once.
  INTERVAL   3 months, chosen once.

and one structural question:

  PICK vs BLEND  it adopts the single best configuration.  Averaging over the
             selection instead - holding a blend of exponents - is the standard
             answer when the choice is noisy, and the fold-by-fold picks in S59
             were visibly noisy (1.0, 1.0, 1.0, 2.5, 1.5, 2.0, 3.0, 2.5).

METHOD: each of the 40 configurations is run ONCE over the whole period and its
daily returns stored.  A switching rule is then just a concatenation of slices,
so the whole grid of rules costs 40 backtests instead of 40 x folds x rules.
The approximation is that a position open across a switch boundary is carried
by the old config's slice rather than re-entered - a boundary effect on ~16 of
1,400 days.  The winner is then re-run honestly, block by block, and both
numbers are reported.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

EXPS = (1.0, 1.5, 2.0, 2.5, 3.0)
GRID = [(p, stp, rr, hold) for p in EXPS for stp in (2.5, 3.0)
        for rr in (2.0, 3.0) for hold in (14, 21)]

_C = {}
def ctx():
    if not _C:
        g = S.grid(S.FULL_START)
        v = S.composite(g, S46.LONG)
        nz = np.abs(v) > 0
        _C.update(g=g, v=v, bm=float(np.abs(v[nz]).mean()), nz=nz, a=g.atr14.to_numpy(float))
    return _C

def shape(p, cap=3.0):
    c = ctx(); v = c["v"]
    u = np.sign(v) * np.abs(v) ** p
    u = u * (c["bm"] / max(np.abs(u[c["nz"]]).mean(), 1e-12))
    return np.sign(u) * np.minimum(np.abs(u), cap)

def full_run(cfg, risk):
    p, stp, rr, hold = cfg
    c = ctx(); u = shape(p); a = c["a"]
    arr = dict(entry=np.nan_to_num(u), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(u)) <= 0.0).astype(float))
    m = backtest(c["g"], arr, "12h", start=S.FULL_START, end=OOS_END, risk=risk,
                 max_lev=10.0, max_bars_h=hold * 24)
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def score(r, how):
    if len(r) < 30 or r.std() == 0: return -9e9
    sh = r.mean() / r.std() * np.sqrt(365.25)
    if how == "sharpe": return sh
    e = np.cumprod(1 + r.to_numpy())
    dd = (e / np.maximum.accumulate(e) - 1).min()
    yrs = max((r.index[-1] - r.index[0]).days / 365.25, 1e-6)
    cagr = e[-1] ** (1 / yrs) - 1
    if how == "calmar": return cagr / abs(dd) if dd < 0 else 9e9
    if how == "sharpe_x_calmar": return sh * (cagr / abs(dd) if dd < 0 else 1.0)
    raise ValueError(how)

def rule(R, how, look, step, blend=0):
    """R: {cfg: daily returns}.  Returns the switched daily-return series."""
    idx = next(iter(R.values())).index
    t0 = idx[0] + pd.DateOffset(months=look)
    segs = []; t = t0; picks = []
    while t < idx[-1]:
        te = min(t + pd.DateOffset(months=step), idx[-1] + pd.Timedelta(days=1))
        tr = (idx >= t - pd.DateOffset(months=look)) & (idx < t)
        te_m = (idx >= t) & (idx < te)
        if te_m.sum() == 0: break
        sc = sorted(((score(r[tr], how), cfg) for cfg, r in R.items()),
                    key=lambda x: -x[0])
        k = blend if blend > 0 else 1
        chosen = [c for _, c in sc[:k]]
        seg = sum(R[c][te_m] for c in chosen) / len(chosen)
        segs.append(seg); picks.append(chosen[0][0]); t = te
    return pd.concat(segs), picks

def stats(r, tag):
    e = np.cumprod(1 + r.to_numpy()); yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((e / np.maximum.accumulate(e) - 1).min()); cagr = e[-1] ** (1 / yrs) - 1
    b = bootstrap_dd(r.to_numpy(), n=2000)
    print(f"{tag:>40} | CAGR {cagr*100:7.1f}%  DD {dd*100:6.1f}%  "
          f"Sharpe {r.mean()/r.std()*np.sqrt(365.25):5.2f}  Calmar {cagr/abs(dd):5.2f}"
          f" | med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")
    return cagr / abs(dd)

if __name__ == "__main__":
    RISK = 0.10
    print(f"caching {len(GRID)} full-period runs at risk {RISK*100:.0f}%...", flush=True)
    R = {cfg: full_run(cfg, RISK) for cfg in GRID}
    print("done\n")
    best = []
    for how in ("sharpe", "calmar", "sharpe_x_calmar"):
        for look in (12, 18, 24):
            for step in (3, 6):
                r, _ = rule(R, how, look, step)
                c = stats(r, f"{how} · look {look}m · step {step}m")
                best.append((c, how, look, step, 0))
    print()
    for blend in (2, 3, 5):
        r, _ = rule(R, "sharpe", 18, 3, blend=blend)
        c = stats(r, f"sharpe · look 18m · step 3m · blend top-{blend}")
        best.append((c, "sharpe", 18, 3, blend))
        r, _ = rule(R, "calmar", 18, 3, blend=blend)
        c = stats(r, f"calmar · look 18m · step 3m · blend top-{blend}")
        best.append((c, "calmar", 18, 3, blend))
    best.sort(key=lambda x: -x[0])
    print("\ntop 5 rules by Calmar:")
    for c, how, look, step, bl in best[:5]:
        print(f"  Calmar {c:5.2f}   {how} · {look}m/{step}m" + (f" · blend {bl}" if bl else ""))
