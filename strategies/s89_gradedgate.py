"""
S89 - Is the gate a threshold or a slope?

S88 settled WHAT the gate reads: price relative to a smoothed reference, not
direction alone and not trend strength.  It did not settle the SHAPE.  Blocking
every short while price is above its average is a step function, and a step is
a strong assumption: it says a short one dollar above the average is as bad as a
short thirty percent above.

Three shapes, all on the short side only (S84 established that gating entries
beats also forcing exits), all as overlays on the existing 40-configuration plan
so the gate shape is isolated from the selection:

    binary      block shorts while px > EMA                 the incumbent
    band d      block shorts only while px > EMA x (1+d)    a dead zone near the average
    near-only   block shorts ONLY between EMA and EMA x1.05 the opposite claim
    taper w     short conviction x clip(1 - (px/EMA-1)/w)   graded, monotone in distance

If `binary` wins, the average itself is the line and the distance carries no
information.  If a `band` wins, the real rule is "do not short far above" and
shorts just above the average were fine.  If `near-only` wins, the damage was
never the melt-ups at all but the chop around the average, and the whole
interpretation from the drawdown attribution is wrong.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest
from research.planscache import cached_plan
from strategies.s69_calsel import ctx, shape, daily
from strategies.s77_lookback import stats

SPAN = 200
_E = {}


def ema_ratio():
    """px / EMA(SPAN) - 1, on the 12h decision grid."""
    if "r" not in _E:
        px = pd.Series(ctx()["g"].close.to_numpy(float))
        e = px.ewm(span=SPAN, adjust=False).mean()
        _E["r"] = (px / e - 1.0).fillna(0.0).to_numpy()
    return _E["r"]


def short_mult(kind, param):
    """Multiplier applied to SHORT conviction, 1.0 = untouched, 0.0 = blocked."""
    r = ema_ratio()
    if kind == "none":
        return np.ones(len(r))
    if kind == "binary":
        return (r <= 0.0).astype(float)
    if kind == "band":
        return (r <= param).astype(float)
    if kind == "near":
        return ~((r > 0.0) & (r <= param)) * 1.0
    if kind == "taper":
        return np.clip(1.0 - np.maximum(r, 0.0) / param, 0.0, 1.0)
    raise ValueError(kind)


def sim(cfg, start, end, risk, kind="none", param=0.0):
    p, stp, rr, hold = cfg
    c = ctx(); u0 = np.nan_to_num(shape(p)); a = c["a"]
    m = short_mult(kind, param)
    u = np.where(u0 < 0, u0 * m, u0)
    arr = dict(entry=u, stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(u0) <= 0.0).astype(float))
    return backtest(c["g"], arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)


def replay(plan, risk, **kw):
    segs, pnl = [], []
    for s, e, cfg in plan:
        m = sim(cfg, s, e, risk, **kw); segs.append(daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))


VARIANTS = [
    ("no gate (control)",        dict(kind="none")),
    ("binary at the average",    dict(kind="binary")),
    ("band, allow to +2%",       dict(kind="band", param=0.02)),
    ("band, allow to +5%",       dict(kind="band", param=0.05)),
    ("band, allow to +10%",      dict(kind="band", param=0.10)),
    ("near-only, block 0 to +5%", dict(kind="near", param=0.05)),
    ("taper over 5%",            dict(kind="taper", param=0.05)),
    ("taper over 10%",           dict(kind="taper", param=0.10)),
    ("taper over 20%",           dict(kind="taper", param=0.20)),
]

if __name__ == "__main__":
    print(f"OVERLAY on the 40-config 12m plan, EMA{SPAN}, short side only, risk 8%\n")
    P = cached_plan(12)
    r = ema_ratio()
    above = (r > 0).mean()
    print(f"price is above EMA{SPAN} on {above:.0%} of bars; "
          f"median distance when above {np.median(r[r > 0]):+.1%}, "
          f"90th pct {np.quantile(r[r > 0], 0.9):+.1%}\n")
    for tag, kw in VARIANTS:
        rr_, pl = replay(P, 0.08, **kw)
        stats(rr_, pl, tag, 0.08)
    print("\ndone: graded gate")
