"""
S77 - Buying back the bear market.

The Calmar-ranked quarterly selection uses a 24-month lookback, which won the
meta-search in S68.  It has a cost nobody priced: the panel cannot begin before
2021-03 (BTC dominance and positioning data both start 2021-01 and need warm-up),
so a 24-month lookback pushes the first tradeable quarter to 2023-03 - and the
2022 bear market falls entirely inside the warm-up.  Every headline number since
S69 has therefore been measured on a window with no bear market in it.

A 12-month lookback selects worse but starts trading in 2022-03, giving a
4.5-year record that contains the drawdown regime.  That is a worse strategy
measured on a harder sample, and it is the more honest number.

Also tested: an ENSEMBLE that runs the 12, 18 and 24-month selections side by
side and holds an equal blend of the three chosen configurations, which hedges
a choice the meta-search made on one sample.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
from strategies.s69_calsel import GRID, sim, daily, calmar_of

RESELECT = 3

def plan(lookback, ref=0.10):
    t0 = pd.Timestamp(S.FULL_START, tz="UTC")
    t = t0 + pd.DateOffset(months=lookback); end = pd.Timestamp(OOS_END, tz="UTC")
    out = []
    while t < end:
        te = min(t + pd.DateOffset(months=RESELECT), end)
        tr0 = t - pd.DateOffset(months=lookback)
        best = None
        for cfg in GRID:
            m = sim(cfg, str(tr0.date()), str(t.date()), ref)
            sc = calmar_of(m)
            if best is None or sc > best[0]: best = (sc, cfg)
        out.append((str(t.date()), str(te.date()), best[1] if best else (1.0, 3.0, 2.0, 21)))
        t = te
    return out

def replay(p, risk, since=None):
    segs, pnl = [], []
    for s, e, cfg in p:
        if since and pd.Timestamp(s, tz="UTC") < pd.Timestamp(since, tz="UTC"): continue
        m = sim(cfg, s, e, risk); segs.append(daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))

def blend(plans, risk, since=None):
    """Hold an equal blend of the configurations the three lookbacks choose."""
    allseg = []
    ref = plans[0]
    for i, (s, e, _) in enumerate(ref):
        if since and pd.Timestamp(s, tz="UTC") < pd.Timestamp(since, tz="UTC"): continue
        rs = []
        for p in plans:
            hit = [c for (a, b, c) in p if a == s]
            if hit: rs.append(daily(sim(hit[0], s, e, risk)))
        if rs:
            allseg.append(pd.DataFrame({j: r for j, r in enumerate(rs)}).fillna(0.0).mean(axis=1))
    return pd.concat(allseg)

def stats(r, P, tag, risk):
    e = np.cumprod(1 + r.to_numpy()); yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((e / np.maximum.accumulate(e) - 1).min()); cagr = e[-1] ** (1/yrs) - 1
    b = bootstrap_dd(r.to_numpy(), n=2500)
    pf = P[P > 0].sum() / max(-P[P < 0].sum(), 1e-9) if len(P) else float("nan")
    ys = {}; es = pd.Series(e, index=r.index); pv = 1.0
    for y, g in es.groupby(es.index.year): ys[int(y)] = float(g.iloc[-1]/pv - 1); pv = g.iloc[-1]
    print(f"{tag:>28}{risk*100:5.0f}% | CAGR {cagr*100:7.1f}%  DD {dd*100:6.1f}%  PF {pf:5.2f}"
          f"  N {len(P):4d}  Shp {r.mean()/r.std()*np.sqrt(365.25):5.2f}  Clm {cagr/abs(dd):5.2f}"
          f" | med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")
    print(f"        {r.index[0].date()} -> {r.index[-1].date()}   yearly " +
          " ".join(f"{y}:{x*100:+.0f}%" for y, x in ys.items()))

if __name__ == "__main__":
    P12, P18, P24 = plan(12), plan(18), plan(24)
    print("=== 12-month lookback: trades from 2022-03, INCLUDES the bear market\n")
    for risk in (0.08, 0.10, 0.12):
        r, p = replay(P12, risk); stats(r, p, "12m lookback", risk)
    print("\n=== 24-month lookback restricted to the same start, for comparison\n")
    for risk in (0.10,):
        r, p = replay(P24, risk); stats(r, p, "24m lookback", risk)
    print("\n=== ensemble of the 12/18/24-month selections\n")
    for risk in (0.08, 0.10, 0.12):
        r = blend([P12, P18, P24], risk)
        stats(r, np.array([]), "12+18+24 blend", risk)
