"""
S83 - The position is sized once and then frozen, and that is a structural leak.

The engine opens a position only when flat and never resizes it.  A marginal
signal that opens a 5%-size long owns the slot for up to the timeout, so a
full-conviction signal arriving two bars later trades at the marginal signal's
size.  Measured on the honest bear-inclusive book (research/blocked.py):

    conviction at entry, mean            0.226   median 0.091
    peak same-sign conviction while held 0.497   median 0.160
    trades whose conviction later >= 2x   37.0%, mean P&L +437 vs -3 for the rest

The book enters at roughly HALF the conviction it goes on to see, and the trades
where conviction rises are the trades that make all the money.  Nothing about
this is a forecasting problem - the information is on a closed bar, in the same
composite the book already trusts for direction.

The fix is a conviction top-up.  While a position is open, if the same-sign
composite reaches `mult` x the conviction the current size was set at, add to the
position so that the loss of the WHOLE package down to the existing stop is
exactly the risk budget the new conviction earns:

    (qty + aq) x |avg_entry_after - stop|  ==  equity x risk x conviction_now

solved exactly for aq, added at the next bar's open with slippage and taker fee,
capped by leverage, and refused when price is already within a quarter of the
original stop distance.  The stop itself never moves, so a top-up can only ever
bring the package back UP to budget - it cannot put more at risk than a fresh
entry at the same conviction would have.

Controls: `mult` 1.5 / 2 / 3 / 5, `max` 1 / 2 / 4 top-ups, and a SHUFFLED control
that tops up on the same schedule with the conviction of a random other bar - if
the gain survives that, it is timing luck rather than the signal.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
import strategies.s45_single as S
from strategies.s69_calsel import ctx, shape, daily
from strategies.s77_lookback import plan, stats

RNG = np.random.default_rng(11)


def sim_add(cfg, start, end, risk, mult=0.0, mx=0, shuffle=False):
    p, stp, rr, hold = cfg
    c = ctx(); u = np.nan_to_num(shape(p)); a = c["a"]
    add = u.copy()
    if shuffle:
        nz = np.abs(u) > 0
        v = np.abs(u[nz]); RNG.shuffle(v)
        add = np.zeros_like(u); add[nz] = np.sign(u[nz]) * v
    arr = dict(entry=u, stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(u) <= 0.0).astype(float), add=add)
    return backtest(c["g"], arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24,
                    add_mult=mult, add_max=mx)


def replay(p, risk, **kw):
    segs, pnl = [], []
    for s, e, cfg in p:
        m = sim_add(cfg, s, e, risk, **kw); segs.append(daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))


VARIANTS = [
    ("no top-up (control)",      dict()),
    ("top-up 2x, max 1",         dict(mult=2.0, mx=1)),
    ("top-up 2x, max 2",         dict(mult=2.0, mx=2)),
    ("top-up 2x, max 4",         dict(mult=2.0, mx=4)),
    ("top-up 1.5x, max 4",       dict(mult=1.5, mx=4)),
    ("top-up 3x, max 4",         dict(mult=3.0, mx=4)),
    ("top-up 5x, max 4",         dict(mult=5.0, mx=4)),
    ("SHUFFLED 2x, max 4",       dict(mult=2.0, mx=4, shuffle=True)),
]

if __name__ == "__main__":
    print("12-month lookback plan (bear-inclusive), selection unchanged\n")
    P12 = plan(12)
    for risk in (0.08,):
        for tag, kw in VARIANTS:
            r, pl = replay(P12, risk, **kw)
            stats(r, pl, tag, risk)
    print("\nrisk ladder on the best top-up rule\n")
    print("done: top-up sweep")
