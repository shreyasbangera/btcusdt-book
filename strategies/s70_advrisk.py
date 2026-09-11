"""
S70 - Letting the selection choose the position size too.

Adaptive risk sizing was dismissed early on the grounds that Sharpe is
size-invariant, so a Sharpe-ranked search would just pick whatever size the
grid topped out at.  That reasoning was right about Sharpe and wrong about the
strategy, because the selection now ranks on CALMAR - and Calmar is NOT
size-invariant.  Drawdown grows roughly linearly with size while compound
return grows sub-linearly, so Calmar has an interior maximum.  A Calmar-ranked
search over size will therefore pick a size, and it will pick the one the
trailing window says was growth-optimal.

That is the Kelly argument, estimated from data rather than assumed, and
re-estimated every quarter.  It is the one remaining place where this book has
a free parameter set by hand.

    grid   exponent x stop x target x hold x RISK
    rank   trailing Calmar over 24 months
    every  3 months, on strictly past data

Controls: the same rule with risk pinned at each fixed level.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46
from strategies.s69_calsel import ctx, shape, sim, daily, calmar_of, stats, LOOKBACK, RESELECT

RISKS = (0.04, 0.06, 0.08, 0.10, 0.12, 0.16)
CFGS = [(p, stp, rr, hold) for p in (1.0, 2.0, 2.5, 3.0)
        for stp in (2.5, 3.0) for rr in (2.0, 3.0) for hold in (14, 21)]

def plan_with_risk(verbose=False):
    t0 = pd.Timestamp(S.FULL_START, tz="UTC")
    t = t0 + pd.DateOffset(months=LOOKBACK); end = pd.Timestamp(OOS_END, tz="UTC")
    out = []
    while t < end:
        te = min(t + pd.DateOffset(months=RESELECT), end)
        tr0 = t - pd.DateOffset(months=LOOKBACK)
        best = None
        for cfg in CFGS:
            for rk in RISKS:
                m = sim(cfg, str(tr0.date()), str(t.date()), rk)
                sc = calmar_of(m)
                if best is None or sc > best[0]: best = (sc, cfg, rk)
        _, cfg, rk = best if best else (0, (1.0, 3.0, 2.0, 21), 0.08)
        out.append((str(t.date()), str(te.date()), cfg, rk))
        if verbose:
            print(f"    {str(t.date())[:7]}  exp {cfg[0]}  {cfg[1]}ATRx{cfg[2]}R {cfg[3]}d  "
                  f"risk {rk*100:.0f}%", flush=True)
        t = te
    return out

def replay(p, scale=1.0):
    segs, pnl = [], []
    for s, e, cfg, rk in p:
        m = sim(cfg, s, e, min(rk * scale, 0.25)); segs.append(daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))

if __name__ == "__main__":
    print(f"grid {len(CFGS)} configs x {len(RISKS)} risk levels, ranked on trailing Calmar\n")
    p = plan_with_risk(verbose=True)
    print()
    for sc in (1.0, 1.25, 1.5):
        r, P = replay(p, sc)
        stats(r, P, f"ADAPTIVE risk x{sc}", 0.0)
    from collections import Counter
    print("\nrisk chosen per quarter:", Counter(f"{x[3]*100:.0f}%" for x in p).most_common())
