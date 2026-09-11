"""
S88 - What is the trend gate actually measuring?

Blocking short entries while price sits above a long exponential average is the
single biggest improvement in this study, and it is also the least explained.
"Price above its average" conflates three different claims:

    direction   the trend is up
    strength    the move is efficient rather than choppy
    level       price is above a reference, whatever the path

S72 measured that book returns track market TRENDINESS at +0.61 - Kaufman's
efficiency ratio, |sum of returns| / sum of |returns|, 1.0 for a straight line
and 0 for pure chop - and S73/S80 showed that trendiness fails as a SIZING
input in both directions because it mean-reverts at the horizon you would need.
It was never tested as a DIRECTIONAL FILTER, which asks nothing of persistence:
the gate only has to describe the bar it is standing on.

So the gate menu is widened from four EMA spans to four different questions,
and the quarterly selection chooses among them causally on trailing Calmar:

    ema<n>   price > EMA(n)                    level + direction, the incumbent
    mom<n>   return over the last n bars > 0    direction alone
    slope<n> EMA(n) higher than n/4 bars ago    direction of the average itself
    er<n>    efficiency ratio over n bars > 0.35 AND the n-bar return > 0
                                                direction AND strength

If the incumbent wins, the gate is about price level. If `mom` matches it, the
level was never the point. If `er` wins, what the gate removes is shorts into
*efficient* up-moves, and the choppy ones were fine to sell.
"""
import sys, json, os; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from strategies.s69_calsel import ctx, shape, daily, calmar_of
from strategies.s77_lookback import stats
import strategies.s45_single as S

LOOKBACK, RESELECT = 12, 3
RANKS = str(_P.RESULTS / "ranks_whatgate.json")
_U = {}


def up_mask(kind, n):
    """True where the gate considers the market to be trending up."""
    key = (kind, n)
    if key not in _U:
        px = pd.Series(ctx()["g"].close.to_numpy(float))
        lr = np.log(px).diff()
        if kind == "ema":
            m = px > px.ewm(span=n, adjust=False).mean()
        elif kind == "mom":
            m = px.pct_change(n) > 0
        elif kind == "slope":
            e = px.ewm(span=n, adjust=False).mean()
            m = e > e.shift(max(n // 4, 1))
        elif kind == "er":
            net = lr.rolling(n).sum()
            gross = lr.abs().rolling(n).sum()
            m = ((net.abs() / gross.replace(0, np.nan)) > 0.35) & (net > 0)
        else:
            raise ValueError(kind)
        _U[key] = m.fillna(False).to_numpy()
    return _U[key]


GATES = [(None, 0)] + [(k, n) for k in ("ema", "mom", "slope", "er") for n in (100, 200)]
GRID = [(p, stp, rr, hold, gk, gn)
        for p in (1.0, 1.5, 2.0, 2.5, 3.0)
        for stp in (2.5, 3.0) for rr in (2.0, 3.0) for hold in (14, 21)
        for (gk, gn) in GATES]


def sim(cfg, start, end, risk):
    p, stp, rr, hold, gk, gn = cfg
    c = ctx(); u = np.nan_to_num(shape(p)); a = c["a"]
    if gk:
        u = np.where((u < 0) & up_mask(gk, gn), 0.0, u)
    arr = dict(entry=u, stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(shape(p))) <= 0.0).astype(float))
    return backtest(c["g"], arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)


def rankings():
    """Checkpointed after every quarter.  The first run of this file died
    silently seven quarters in and lost all of it, because the cache was only
    written at the end."""
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
        te = min(t + pd.DateOffset(months=RESELECT), end)
        key = str(t.date())
        if key in done:
            out.append(done[key]); t = te; continue
        tr0 = t - pd.DateOffset(months=LOOKBACK)
        sc = sorted(((calmar_of(sim(cfg, str(tr0.date()), key, 0.10)), cfg)
                     for cfg in GRID), key=lambda x: -x[0])
        out.append((key, str(te.date()), [c for _, c in sc]))
        b = sc[0][1]
        print(f"    {key[:7]}  exp {b[0]} {b[1]}ATR x{b[2]}R {b[3]}d  "
              f"gate {(str(b[4]) + str(b[5])) if b[4] else 'none':>8}  Calmar {sc[0][0]:.2f}",
              flush=True)
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
    print(f"{len(GRID)} configurations, gate menu {[f'{k}{n}' for k, n in GATES if k]}\n")
    R = rankings()
    from collections import Counter
    c1 = Counter((cs[0][4] or "none") for _, _, cs in R)
    c5 = Counter((cfg[4] or "none") for _, _, cs in R for cfg in cs[:5])
    print(f"\ntop-1 gate kind : {dict(c1)}")
    print(f"top-5 gate kind : {dict(c5)}  (of {5*len(R)})\n")
    for k in (1, 3, 5):
        r, pl = blend(R, k, 0.08); stats(r, pl, f"whatgate top-{k}", 0.08)
    print("\ndone: whatgate")
