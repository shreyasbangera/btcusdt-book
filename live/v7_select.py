#!/usr/bin/env python3
"""
Quarterly selection for V7.  Run on 1 Jan / 1 Apr / 1 Jul / 1 Oct.

Ranks all 200 configurations by their Calmar over the trailing TWELVE months
and writes the best three to the plan file the runner reads.  The window ends
today, so nothing after the decision date is used — this is the same rule the
backtest applies, executed forward.
"""
import os, sys, json, argparse
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import pandas as pd
from strategies.s87_combined import GRID, sim
from strategies.s69_calsel import calmar_of
from live.runner import STORE

PLAN = os.path.join(STORE, "v7_plan.json")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asof", default=str(pd.Timestamp.utcnow().date()),
                    help="decision date; the lookback ends here")
    ap.add_argument("--k", type=int, default=3, help="sleeves to hold")
    ap.add_argument("--out", default=PLAN)
    a = ap.parse_args()

    end = pd.Timestamp(a.asof, tz="UTC")
    start = end - pd.DateOffset(months=12)
    print(f"ranking {len(GRID)} configurations on {start.date()} -> {end.date()}\n")
    sc = []
    for n, cfg in enumerate(GRID, 1):
        m = sim(cfg, str(start.date()), str(end.date()), 0.10)
        sc.append((calmar_of(m), cfg))
        if n % 25 == 0:
            print(f"  {n}/{len(GRID)}", flush=True)
    sc.sort(key=lambda x: -x[0])

    print(f"\ntop {a.k} by trailing Calmar:")
    for r, (c, cfg) in enumerate(sc[:a.k], 1):
        p, stp, rr, hold, gsp, gmd = cfg
        g = f"ema{gsp}" if gsp else "none"
        print(f"  {r}. exp {p}  {stp}ATR x{rr}R  {hold}d  gate {g:>7}   Calmar {c:.2f}")

    plan = dict(asof=str(end.date()),
                lookback_months=12,
                configs=[[c[0], c[1], c[2], c[3], ("ema" if c[4] else None), c[4]]
                         for _, c in sc[:a.k]],
                note="fields: exponent, stop_atr, reward_risk, hold_days, gate_kind, gate_span")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(plan, open(a.out, "w"), indent=1)
    print(f"\nwrote {a.out}")
