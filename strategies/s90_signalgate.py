"""
S90 - Gate the signals, not the net.

The trend gate is blunt: it zeroes the whole composite's short side while price
is above its average, regardless of which signals were asking to be short.  The
drawdown attribution says that is heavier than necessary.  Inside the worst
episode (2024-10 -> 2025-02) the damage was concentrated:

    flow   agreeing with the trade   -805     (+14,443 everywhere else)
    ivol   agreeing                  -415     ( +8,869)
    btcdom agreeing                  -396     ( +5,408)
    posn   OPPOSING the trade        -596     (   -965 across all 721 other trades)
    cmpx   agreeing                  +271     (+15,430)

`cmpx` made money inside the melt-up.  Gating it costs something and buys
nothing.  So: apply the gate to ONE signal's short contribution at a time and
see which signals are actually the problem.

Multiple-testing exposure, stated first: six signals, one sample, so the best of
six is expected to look good by luck alone.  Nothing here is adopted on this
evidence - a winner would have to survive the causal quarterly selection the way
the net-level gate did in S85.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest
from research.planscache import cached_plan
from strategies.s69_calsel import ctx, daily
from strategies.s77_lookback import stats
import strategies.s45_single as S
import strategies.s46_net as S46

SPAN = 200
_E = {}


def up():
    if "u" not in _E:
        px = pd.Series(ctx()["g"].close.to_numpy(float))
        _E["u"] = (px > px.ewm(span=SPAN, adjust=False).mean()).fillna(False).to_numpy()
    return _E["u"]


NAMES = S46.LONG          # the five signals the book actually trades

def composite(gated=()):
    """The book's own composite, with the named signals' SHORT contribution
    suppressed while price is above its average.

    Built from s45.unit so it is identical to the traded book when `gated` is
    empty.  The first version of this file iterated S46.SHORT, which adds the
    implied-volatility signal as a hard zero for the 15 months before BVOL
    exists - diluting every other signal by a sixth and making the control a
    different, worse book (62.6% at -25.7% against the real 73.2% at -14.8%).
    Nothing was concluded from that run."""
    g = ctx()["g"]; u = up()
    parts = []
    for n in NAMES:
        c = S.unit(g, n)
        if n in gated:
            c = np.where((c < 0) & u, 0.0, c)
        parts.append(c)
    return np.mean(np.vstack(parts), axis=0)


def shaped(v, p, cap=3.0):
    nz = np.abs(v) > 0
    if not nz.any(): return v
    x = np.sign(v) * np.abs(v) ** p
    x = x * (float(np.abs(v[nz]).mean()) / max(float(np.abs(x[nz]).mean()), 1e-12))
    return np.sign(x) * np.minimum(np.abs(x), cap)


def sim(cfg, start, end, risk, gated=()):
    p, stp, rr, hold = cfg
    c = ctx(); a = c["a"]
    u = np.nan_to_num(shaped(composite(gated), p))
    arr = dict(entry=u, stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(u) <= 0.0).astype(float))
    return backtest(c["g"], arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)


def replay(plan, risk, gated=()):
    segs, pnl = [], []
    for s, e, cfg in plan:
        m = sim(cfg, s, e, risk, gated); segs.append(daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))


if __name__ == "__main__":
    print(f"OVERLAY on the 40-config 12m plan, EMA{SPAN}, risk 8%\n")
    P = cached_plan(12)
    runs = [("no gate (control)", ())] \
         + [(f"gate {n} only", (n,)) for n in NAMES] \
         + [("gate ALL (the net gate)", tuple(NAMES)),
            ("gate all but cmpx", tuple(n for n in NAMES if n != "cmpx"))]
    for tag, g in runs:
        r, pl = replay(P, 0.08, g)
        stats(r, pl, tag, 0.08)
    print("\ndone: signal gate")
