"""
S83b - The conviction top-up, with the sizing bug taken out.

S83's first mechanism held the stop fixed and solved for the quantity that
brought the package back to budget:

    aq = (budget - qty x |entry - stop|) / |add_price - stop|

The denominator is the distance from the CURRENT price to the stop, and that
distance shrinks as a trade loses.  So the rule added hardest into losers and
refused to add at all once a trade was far enough in front that qty x |entry -
stop| already exceeded budget.  It was an averaging-down machine wearing a risk
budget as a disguise, and the drawdowns showed it: -14.8% became -30% to -47%.

The shuffled control is what says the idea itself is still alive.  Topping up on
the same schedule with a random other bar's conviction returned 60.8%; topping
up on the real conviction returned 73.3% at almost identical drawdown.  The
signal content is real - the risk handling was wrong.

Two repaired modes, neither with any price feedback in the sizing:

    mode 1  target quantity = budget / original_risk_unit, i.e. exactly the size
            a fresh entry at this conviction would take, with the stop reset to
            one risk unit from the new average entry and the target to one target
            unit, so total risk is the budget by construction
    mode 2  mode 1, and only while the trade is not in loss - a top-up may
            reinforce a position the market is already agreeing with, never
            rescue one it is not
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest
from strategies.s69_calsel import ctx, shape, daily
from strategies.s77_lookback import plan, stats

RNG = np.random.default_rng(11)


def sim_add(cfg, start, end, risk, mult=0.0, mx=0, mode=0, shuffle=False):
    p, stp, rr, hold = cfg
    c = ctx(); u = np.nan_to_num(shape(p)); a = c["a"]
    add = u.copy()
    if shuffle:
        nz = np.abs(u) > 0
        v = np.abs(u[nz]).copy(); RNG.shuffle(v)
        add = np.zeros_like(u); add[nz] = np.sign(u[nz]) * v
    arr = dict(entry=u, stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(u) <= 0.0).astype(float), add=add)
    return backtest(c["g"], arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24,
                    add_mult=mult, add_max=mx, add_mode=mode)


def replay(p, risk, **kw):
    segs, pnl = [], []
    for s, e, cfg in p:
        m = sim_add(cfg, s, e, risk, **kw); segs.append(daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))


VARIANTS = [
    ("no top-up (control)",        dict()),
    ("m1 conviction-unit 2x, 1",   dict(mult=2.0, mx=1, mode=1)),
    ("m1 conviction-unit 2x, 4",   dict(mult=2.0, mx=4, mode=1)),
    ("m1 conviction-unit 3x, 4",   dict(mult=3.0, mx=4, mode=1)),
    ("m2 winners only 1.5x, 4",    dict(mult=1.5, mx=4, mode=2)),
    ("m2 winners only 2x, 1",      dict(mult=2.0, mx=1, mode=2)),
    ("m2 winners only 2x, 2",      dict(mult=2.0, mx=2, mode=2)),
    ("m2 winners only 2x, 4",      dict(mult=2.0, mx=4, mode=2)),
    ("m2 winners only 3x, 4",      dict(mult=3.0, mx=4, mode=2)),
    ("m2 SHUFFLED 2x, 4",          dict(mult=2.0, mx=4, mode=2, shuffle=True)),
]

if __name__ == "__main__":
    print("12-month lookback plan (bear-inclusive), selection unchanged, risk 8%\n")
    P12 = plan(12)
    for tag, kw in VARIANTS:
        r, pl = replay(P12, 0.08, **kw)
        stats(r, pl, tag, 0.08)
    print("\ndone: topup2 sweep")
