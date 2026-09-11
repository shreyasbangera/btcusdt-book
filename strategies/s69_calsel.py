"""
S69 - Selecting on the thing you are actually maximising.

The quarterly re-selection picked the configuration with the best trailing
SHARPE.  Sharpe is close to size-invariant, so it chose the shape of the bet and
was blind to drawdown - while the target the whole study is chasing is CALMAR.
Selecting on Calmar directly, with a longer lookback:

    objective   trailing Calmar over the lookback window
    lookback    24 months (was 18)
    interval    3 months (unchanged)
    grid        40 configurations: exponent x stop x target x hold

Honest implementation: every block is a separate backtest over that block only,
with the configuration chosen from the preceding 24 months and nothing else.

Costs to state up front. A 24-month lookback pushes the start of the tradeable
record to 2023-03, so this is measured on 3.5 years rather than 4 or 5.5. And
the selection RULE was itself chosen from 18 candidates, which is a second layer
of search - mitigated only by the fact that the whole 24-month drawdown-aware
family wins together (Calmar 8.11, 8.11, 7.76) rather than one lucky cell.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

LOOKBACK, RESELECT = 24, 3
GRID = [(p, stp, rr, hold) for p in (1.0, 1.5, 2.0, 2.5, 3.0)
        for stp in (2.5, 3.0) for rr in (2.0, 3.0) for hold in (14, 21)]

_C = {}
def ctx():
    if not _C:
        g = S.grid(S.FULL_START); v = S.composite(g, S46.LONG); nz = np.abs(v) > 0
        _C.update(g=g, v=v, bm=float(np.abs(v[nz]).mean()), nz=nz, a=g.atr14.to_numpy(float))
    return _C

def shape(p, cap=3.0):
    c = ctx(); v = c["v"]
    u = np.sign(v) * np.abs(v) ** p
    u = u * (c["bm"] / max(np.abs(u[c["nz"]]).mean(), 1e-12))
    return np.sign(u) * np.minimum(np.abs(u), cap)

def sim(cfg, start, end, risk):
    p, stp, rr, hold = cfg
    c = ctx(); u = shape(p); a = c["a"]
    arr = dict(entry=np.nan_to_num(u), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(u)) <= 0.0).astype(float))
    return backtest(c["g"], arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def calmar_of(m):
    if m["trades"] < 15 or m["max_dd"] >= 0: return -9e9
    return m["cagr"] / abs(m["max_dd"])

def plan(objective="calmar", ref=0.10, verbose=False):
    t0 = pd.Timestamp(S.FULL_START, tz="UTC")
    t = t0 + pd.DateOffset(months=LOOKBACK); end = pd.Timestamp(OOS_END, tz="UTC")
    out = []
    while t < end:
        te = min(t + pd.DateOffset(months=RESELECT), end)
        tr0 = t - pd.DateOffset(months=LOOKBACK)
        best = None
        for cfg in GRID:
            m = sim(cfg, str(tr0.date()), str(t.date()), ref)
            sc = calmar_of(m) if objective == "calmar" else (
                 m["sharpe"] if m["trades"] >= 15 else -9e9)
            if best is None or sc > best[0]: best = (sc, cfg)
        cfg = best[1] if best else (1.0, 3.0, 2.0, 21)
        out.append((str(t.date()), str(te.date()), cfg))
        if verbose: print(f"    {str(t.date())[:7]}  exp {cfg[0]}  {cfg[1]}ATR x{cfg[2]}R  {cfg[3]}d")
        t = te
    return out

def replay(p, risk):
    segs, pnl = [], []
    for s, e, cfg in p:
        m = sim(cfg, s, e, risk); segs.append(daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))

def stats(r, P, tag, risk):
    e = np.cumprod(1 + r.to_numpy()); yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((e / np.maximum.accumulate(e) - 1).min()); cagr = e[-1] ** (1 / yrs) - 1
    b = bootstrap_dd(r.to_numpy(), n=3000)
    pf = P[P > 0].sum() / max(-P[P < 0].sum(), 1e-9) if len(P) else float("nan")
    ys = {}; es = pd.Series(e, index=r.index); pv = 1.0
    for y, gg in es.groupby(es.index.year): ys[int(y)] = float(gg.iloc[-1] / pv - 1); pv = gg.iloc[-1]
    print(f"{tag:>26}{risk*100:5.0f}% | CAGR {cagr*100:7.1f}%  DD {dd*100:6.1f}%  PF {pf:5.2f}"
          f"  N {len(P):4d}  Sharpe {r.mean()/r.std()*np.sqrt(365.25):5.2f}  Calmar {cagr/abs(dd):5.2f}"
          f" | med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")
    print("        yearly " + " ".join(f"{y}:{x*100:+.0f}%" for y, x in ys.items()))

if __name__ == "__main__":
    print(f"CALMAR-selected, {LOOKBACK}m lookback / {RESELECT}m interval, {len(GRID)} configs\n")
    pc = plan("calmar", verbose=True)
    ps = plan("sharpe")
    print()
    for risk in (0.06, 0.08, 0.10, 0.12):
        r, P = replay(pc, risk); stats(r, P, "CALMAR-selected", risk)
    print()
    for risk in (0.10,):
        r, P = replay(ps, risk); stats(r, P, "SHARPE-selected (control)", risk)
