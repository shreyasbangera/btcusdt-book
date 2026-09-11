"""
S87 - Both improvements at once, and a span-robustness test the gate has to pass.

Two things worked independently:

    S85  the trend gate, chosen causally each quarter, 80.6% at -13.7% against
         73.2% at -14.8%, and 134.5% at exactly the -20.0% gate at 12% risk
    S86  holding the top k configurations instead of the top 1, Calmar 4.94 to
         5.27 with no new rule fitted

They should compose: the gate changes which trades are taken, the blend changes
how many configurations take them.

This also fixes the one thing S85 could not.  The gate menu there was {EMA100,
EMA200} and both spans were picked after looking at the full sample - the
per-quarter selection was causal but the MENU was not.  Widening the menu to
{100, 150, 200, 300} tests whether the effect is a property of trend gating or of
one lucky span: a real effect should survive the selection being handed spans
that were never inspected, and should show up as the selection choosing SOME gate
in most quarters rather than one specific number.

    grid   5 exponents x 2 stops x 2 targets x 2 holds x 5 gates = 200 configs
    rank   trailing Calmar over the preceding 12 months, refit quarterly
    hold   top k at risk/k, k in {1, 3, 5, 8, 12}
"""
import sys, json, os; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import OOS_END
from strategies.s69_calsel import daily, calmar_of
from strategies.s84_gate import sim_gate
from strategies.s77_lookback import stats
import strategies.s45_single as S

LOOKBACK, RESELECT = 12, 3
GATES = [(0, ""), (100, "s"), (150, "s"), (200, "s"), (300, "s")]
GRID = [(p, stp, rr, hold, sp, md)
        for p in (1.0, 1.5, 2.0, 2.5, 3.0)
        for stp in (2.5, 3.0) for rr in (2.0, 3.0) for hold in (14, 21)
        for (sp, md) in GATES]
RANKS = str(_P.RESULTS / "ranks_gate200.json")


def sim(cfg, start, end, risk):
    p, stp, rr, hold, sp, md = cfg
    return sim_gate((p, stp, rr, hold), start, end, risk, span=sp, mode=md)


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
        b = sc[0][1]
        print(f"    {str(t.date())[:7]}  exp {b[0]} {b[1]}ATR x{b[2]}R {b[3]}d  "
              f"gate {'EMA'+str(b[4]) if b[4] else 'none':>7}  Calmar {sc[0][0]:.2f}", flush=True)
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
    print(f"{len(GRID)} configurations, gate menu {[g[0] for g in GATES]}\n")
    R = rankings()
    from collections import Counter
    c1 = Counter(cs[0][4] for _, _, cs in R)
    c5 = Counter(cfg[4] for _, _, cs in R for cfg in cs[:5])
    print(f"\ntop-1 gate choices : {dict(c1)}")
    print(f"top-5 gate choices : {dict(c5)}  (of {5*len(R)})\n")
    for k in (1, 3, 5, 8, 12):
        r, pl = blend(R, k, 0.08); stats(r, pl, f"gated top-{k}", 0.08)
    print("\nrisk ladder on the top-5 gated blend\n")
    for risk in (0.10, 0.12, 0.14, 0.16):
        r, pl = blend(R, 5, risk); stats(r, pl, "gated top-5", risk)
    print("\ndone: combined")
