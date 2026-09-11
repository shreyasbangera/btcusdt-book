"""
S86b - Is the blend gain diversification, or the ranking?

Holding the top k configurations by trailing Calmar beats holding the top 1:

    k      1       2       3       5       8      12      20
    CAGR  73.2    74.5    83.1    87.7    85.4    85.4    81.6
    DD   -14.8   -16.4   -16.7   -17.5   -16.7   -16.2   -21.9
    Clm   4.94    4.55    4.99    5.02    5.11    5.27    3.72

Broad and smooth from k=3 to k=12, which is what a real effect looks like, and
it needs nothing new fitted - the ranking rule is the one already in use.

Two questions remain.  Is the gain the RANKING (the top k are better than
average) or just DIVERSIFICATION (any k would do)?  A random-k control answers
it.  And what does the blend return at the risk that puts realised drawdown on
the 20% gate, which is the only number the brief cares about?
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from strategies.s69_calsel import GRID, sim, daily
from strategies.s86_topk import rankings, blend
from strategies.s77_lookback import stats

RNG = np.random.default_rng(7)


def blend_random(R, k, risk, seed=0):
    rng = np.random.default_rng(seed)
    segs, pnl = [], []
    for s, e, _cfgs in R:
        pick = [GRID[j] for j in rng.choice(len(GRID), size=k, replace=False)]
        rs = []
        for cfg in pick:
            m = sim(cfg, s, e, risk / k); rs.append(daily(m))
            td = m["trades_df"]
            if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
        segs.append(pd.DataFrame({j: r for j, r in enumerate(rs)}).fillna(0.0).sum(axis=1))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))


if __name__ == "__main__":
    R = rankings()
    print("RANDOM-k control: k configurations drawn at random each quarter\n")
    for seed in (1, 2, 3):
        r, pl = blend_random(R, 5, 0.08, seed=seed)
        stats(r, pl, f"random-5 (seed {seed})", 0.08)
    print("\nrisk ladder on the top-5 blend\n")
    for risk in (0.08, 0.09, 0.10, 0.11, 0.12):
        r, pl = blend(R, 5, risk); stats(r, pl, "top-5 blended", risk)
    print("\nrisk ladder on the top-12 blend\n")
    for risk in (0.08, 0.10, 0.11, 0.12, 0.14):
        r, pl = blend(R, 12, risk); stats(r, pl, "top-12 blended", risk)
    print("\ndone: blend ladder")
