"""
S85 - The trend gate, chosen causally.

S84 measured a trend gate as an overlay and read the answer off the full sample,
which is exactly how the selection illusion in S76 was manufactured.  Here the
gate is demoted to one more axis of the quarterly grid and has to earn its place
the same way every other parameter does: each quarter, the configuration with the
best trailing Calmar over the preceding 12 months is chosen from the 12 months
BEFORE that quarter and nothing else, then traded blind through it.

    grid   5 exponents x 2 stops x 2 targets x 2 holds x 3 gates = 120 configs
    gates  none | block shorts above EMA100 | block shorts above EMA200

If the gate is real the selection will reach for it in the quarters where trend
is strong and drop it elsewhere, and the assembled record will beat the 40-config
control.  If it is a story fitted to one drawdown, the selection will pick it at
random and the record will be no better - or worse, because a 3x bigger grid is
3x more chances for a lucky trailing Calmar.

The control is the same 40-config plan without the gate axis, so the comparison
prices the extra search as well as the idea.
"""
import sys, json, os; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import OOS_END
from research.planscache import cached_plan
from strategies.s69_calsel import ctx, shape, daily, calmar_of
from strategies.s84_gate import sim_gate
from strategies.s77_lookback import stats
import strategies.s45_single as S

RESELECT = 3
GATES = [(0, ""), (100, "s"), (200, "s")]
GRID = [(p, stp, rr, hold, sp, md)
        for p in (1.0, 1.5, 2.0, 2.5, 3.0)
        for stp in (2.5, 3.0) for rr in (2.0, 3.0) for hold in (14, 21)
        for (sp, md) in GATES]
CACHE = str(_P.RESULTS / "plan_gate.json")


def sim(cfg, start, end, risk):
    p, stp, rr, hold, sp, md = cfg
    return sim_gate((p, stp, rr, hold), start, end, risk, span=sp, mode=md)


def plan(lookback=12, ref=0.10):
    if os.path.exists(CACHE):
        return [(s, e, tuple(c)) for s, e, c in json.load(open(CACHE))]
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
        cfg = best[1] if best else (1.0, 3.0, 2.0, 21, 0, "")
        out.append((str(t.date()), str(te.date()), cfg))
        print(f"    {str(t.date())[:7]}  exp {cfg[0]}  {cfg[1]}ATR x{cfg[2]}R  {cfg[3]}d  "
              f"gate {'EMA'+str(cfg[4]) if cfg[4] else 'none':>7}", flush=True)
        t = te
    json.dump([[s, e, list(c)] for s, e, c in out], open(CACHE, "w"), indent=1)
    return out


def replay(p, risk):
    segs, pnl = [], []
    for s, e, cfg in p:
        m = sim(cfg, s, e, risk); segs.append(daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))


if __name__ == "__main__":
    print(f"{len(GRID)} configurations, 12-month lookback, quarterly\n")
    PG = plan(12)
    ng = sum(1 for _, _, c in PG if c[4])
    print(f"\ngate chosen in {ng} of {len(PG)} quarters\n")
    from strategies.s83b_topup import replay as rep0
    P0 = cached_plan(12)
    for risk in (0.08, 0.10, 0.12):
        r, pl = rep0(P0, risk); stats(r, pl, "40-config control", risk)
    print()
    for risk in (0.08, 0.10, 0.12):
        r, pl = replay(PG, risk); stats(r, pl, "120-config with gate", risk)
    print("\ndone: gate grid")
