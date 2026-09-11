"""
S91 - Does gating funding survive being chosen causally?

S90 found that gating only the FUNDING signal's short side beats gating the
whole composite - Calmar 7.43 against 5.14, and the only variant that raises
Sharpe rather than buying Calmar out of the drawdown.  That was an overlay read
off the full sample, with five signals tested, so the best of five flatters
itself by construction.

Here the choice is demoted to an axis of the quarterly grid.  Each quarter the
rule picks the configuration with the best Calmar over the preceding twelve
months, from the twelve before that and nothing else, and trades it blind:

    gate   none | the whole short side above EMA200 | funding's short side above EMA200
    grid   5 exponents x 2 stops x 2 targets x 2 holds x 3 gates = 120 configs

120 is the same grid size that worked in S85, deliberately - S88 showed that
widening the menu to 360 cost the selection more than the extra candidates were
worth.  The control is the 40-config ungated plan, so the comparison prices the
3x larger search as well as the idea.
"""
import sys, json, os; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from research.planscache import cached_plan
from strategies.s69_calsel import ctx, daily, calmar_of
from strategies.s90_signalgate import composite, shaped, up
from strategies.s77_lookback import stats
import strategies.s45_single as S

LOOKBACK, RESELECT = 12, 3
GATES = ["none", "net", "fundz"]
GRID = [(p, stp, rr, hold, g)
        for p in (1.0, 1.5, 2.0, 2.5, 3.0)
        for stp in (2.5, 3.0) for rr in (2.0, 3.0) for hold in (14, 21)
        for g in GATES]
RANKS = str(_P.RESULTS / "ranks_fundgate.json")


def sim(cfg, start, end, risk):
    p, stp, rr, hold, g = cfg
    c = ctx(); a = c["a"]
    v = composite(("fundz",) if g == "fundz" else ())
    u = np.nan_to_num(shaped(v, p))
    if g == "net":
        u = np.where(u < 0, np.where(up(), 0.0, u), u)
    arr = dict(entry=u, stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(u) <= 0.0).astype(float))
    return backtest(c["g"], arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)


def rankings():
    part = RANKS + ".part"
    done = {}
    for f in (RANKS, part):
        if os.path.exists(f):
            for s_, e_, cs in json.load(open(f)):
                done[s_] = (s_, e_, [tuple(c) for c in cs])
    t0 = pd.Timestamp(S.FULL_START, tz="UTC")
    t = t0 + pd.DateOffset(months=LOOKBACK); end = pd.Timestamp(OOS_END, tz="UTC")
    out = []
    while t < end:
        te = min(t + pd.DateOffset(months=RESELECT), end); key = str(t.date())
        if key in done:
            out.append(done[key]); t = te; continue
        tr0 = t - pd.DateOffset(months=LOOKBACK)
        sc = sorted(((calmar_of(sim(cfg, str(tr0.date()), key, 0.10)), cfg) for cfg in GRID),
                    key=lambda x: -x[0])
        out.append((key, str(te.date()), [c for _, c in sc]))
        b = sc[0][1]
        print(f"    {key[:7]}  exp {b[0]} {b[1]}ATR x{b[2]}R {b[3]}d  gate {b[4]:>5}"
              f"   Calmar {sc[0][0]:.2f}", flush=True)
        json.dump([[a_, b_, [list(c) for c in cs]] for a_, b_, cs in out], open(part, "w"))
        t = te
    json.dump([[a_, b_, [list(c) for c in cs]] for a_, b_, cs in out], open(RANKS, "w"))
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
    print(f"{len(GRID)} configurations, gates {GATES}\n")
    R = rankings()
    from collections import Counter
    print(f"\ntop-1 gate : {dict(Counter(cs[0][4] for _, _, cs in R))}")
    print(f"top-3 gate : {dict(Counter(c[4] for _, _, cs in R for c in cs[:3]))}"
          f"  (of {3*len(R)})\n")
    for k in (1, 3, 5):
        r, pl = blend(R, k, 0.08); stats(r, pl, f"fundgate top-{k}", 0.08)
    print("\ndone: fundgate")
