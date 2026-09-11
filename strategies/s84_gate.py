"""
S84 - The worst drawdown is 29 shorts taken into the strongest trend of the sample.

Attribution of the deepest episode (2024-10-17 -> 2025-02-23, -14.8%, 129 days):

    50 trades, total P&L -1,516, win rate 48% (against 47% everywhere else)
        long      21 trades     -165
        short     29 trades   -1,351      <- 89% of the loss

The hit rate does not collapse; the book simply keeps selling a market that keeps
going up, and the losses are bigger than the wins.  By signal, inside the window,
flow agreeing loses 805 and posn opposing loses 596 - while everywhere else posn
agreeing is the single biggest earner in the whole study at +29,441.

This is the classic failure mode of crowding data: positioning and funding turn
contrarian early in a melt-up and stay wrong for months.

The obvious rule is a trend gate, and the obvious danger is that the rule was
derived by looking at the worst window.  So this file only measures the overlay.
Nothing here is adopted; if a gate looks real it goes into the quarterly grid in
S85 and has to be chosen causally, quarter by quarter, on trailing Calmar alone.

    EMA span on the 12h decision grid: 100 bars (50d) and 200 bars (100d)
    g_short  suppress SHORT entries while close > EMA
    g_long   suppress LONG entries while close < EMA
    g_both   both
    +exit    also flatten an open position the moment the gate turns against it
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest
from research.planscache import cached_plan
from strategies.s69_calsel import ctx, shape, daily
from strategies.s77_lookback import stats


_T = {}
def trend(span):
    if span not in _T:
        c = ctx()
        px = pd.Series(c["g"].close.to_numpy(float))
        _T[span] = (px > px.ewm(span=span, adjust=False).mean()).to_numpy()
    return _T[span]


def sim_gate(cfg, start, end, risk, span=0, mode="", force_exit=False):
    p, stp, rr, hold = cfg
    c = ctx(); u0 = np.nan_to_num(shape(p)); u = u0; a = c["a"]
    if span:
        up = trend(span)
        block = np.zeros(len(u), bool)
        if "s" in mode: block |= (u < 0) & up
        if "l" in mode: block |= (u > 0) & ~up
        u = np.where(block, 0.0, u)
    arr = dict(entry=u, stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(u) <= 0.0).astype(float) if force_exit
                    else (np.abs(u0) <= 0.0).astype(float))
    return backtest(c["g"], arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)


def replay(p, risk, **kw):
    segs, pnl = [], []
    for s, e, cfg in p:
        m = sim_gate(cfg, s, e, risk, **kw); segs.append(daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))


VARIANTS = [
    ("no gate (control)",          dict()),
    ("EMA100 block shorts",        dict(span=100, mode="s")),
    ("EMA100 block shorts +exit",  dict(span=100, mode="s", force_exit=True)),
    ("EMA200 block shorts",        dict(span=200, mode="s")),
    ("EMA200 block shorts +exit",  dict(span=200, mode="s", force_exit=True)),
    ("EMA200 block longs",         dict(span=200, mode="l")),
    ("EMA200 block both",          dict(span=200, mode="sl")),
    ("EMA200 block both +exit",    dict(span=200, mode="sl", force_exit=True)),
]

if __name__ == "__main__":
    print("OVERLAY ONLY - the gate is not in the selection grid.  12m plan, risk 8%\n")
    P12 = cached_plan(12)
    for tag, kw in VARIANTS:
        r, pl = replay(P12, 0.08, **kw)
        stats(r, pl, tag, 0.08)
    print("\ndone: gate overlay")
