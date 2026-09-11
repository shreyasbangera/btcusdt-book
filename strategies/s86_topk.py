"""
S86 - Pick one configuration, or hold several?

The quarterly selection keeps exactly one configuration per quarter: the best
trailing Calmar out of 40.  That is a bet on the ranking being informative at the
top, and it throws away whatever diversification the runners-up would have added.
A single account can hold the net of several configurations at once - they all
trade the same instrument, so the positions simply add - and if the configurations
disagree about when to be in the market, the blended path should be smoother than
any one of them.

S77 already found that blending the 12/18/24-month LOOKBACKS lost to picking, but
those three selections agree with each other most quarters.  Configurations
differ in exponent, stop, target and hold, so they disagree far more often.

Protocol: rank all 40 configurations each quarter by trailing Calmar over the
preceding 12 months - exactly the existing rule, nothing new is fitted - then
hold the top k in equal risk fractions.  k=1 is the current book.

Blending equity curves at risk/k is the faithful model of a netted account here:
P&L is additive in a single account, and where two sleeves take opposite sides the
real account would pay LESS in fees than the blend charges, so this is the
conservative side of the approximation.
"""
import sys, json, os; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import OOS_END
from strategies.s69_calsel import GRID, sim, daily, calmar_of
from strategies.s77_lookback import stats
import strategies.s45_single as S

LOOKBACK, RESELECT = 12, 3
RANKS = str(_P.RESULTS / "ranks12.json")


def rankings():
    if os.path.exists(RANKS):
        return [(s, e, [tuple(c) for c in cs]) for s, e, cs in json.load(open(RANKS))]
    t0 = pd.Timestamp(S.FULL_START, tz="UTC")
    t = t0 + pd.DateOffset(months=LOOKBACK); end = pd.Timestamp(OOS_END, tz="UTC")
    out = []
    while t < end:
        te = min(t + pd.DateOffset(months=RESELECT), end)
        tr0 = t - pd.DateOffset(months=LOOKBACK)
        sc = []
        for cfg in GRID:
            m = sim(cfg, str(tr0.date()), str(t.date()), 0.10)
            sc.append((calmar_of(m), cfg))
        sc.sort(key=lambda x: -x[0])
        out.append((str(t.date()), str(te.date()), [c for _, c in sc]))
        print(f"    {str(t.date())[:7]}  best {sc[0][1]}  Calmar {sc[0][0]:.2f}", flush=True)
        t = te
    json.dump([[s, e, [list(c) for c in cs]] for s, e, cs in out], open(RANKS, "w"))
    return out


def blend(R, k, risk):
    segs, pnl = [], []
    for s, e, cfgs in R:
        rs = []
        for cfg in cfgs[:k]:
            m = sim(cfg, s, e, risk / k); rs.append(daily(m))
            td = m["trades_df"]
            if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
        segs.append(pd.DataFrame({j: r for j, r in enumerate(rs)}).fillna(0.0).sum(axis=1))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))


if __name__ == "__main__":
    R = rankings()
    print()
    for k in (1, 2, 3, 5, 8, 12, 20):
        r, pl = blend(R, k, 0.08)
        stats(r, pl, f"top-{k} blended", 0.08)
    print("\ndone: topk blend")
