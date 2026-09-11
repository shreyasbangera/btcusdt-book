"""
S82 - Trade geometry conditioned on conviction.

Everywhere in this study the conviction |net| has done exactly one job: it scales
the SIZE of the bet.  The geometry of the trade - how far the stop sits, how far
the target sits - is uniform across every trade in a quarter, chosen by the
quarterly grid and applied identically to a 0.3-sigma signal and a 3.0-sigma one.

That is an assumption, not a result.  If a strong composite reading precedes a
LARGER move, then the right geometry for it is a wider stop and a farther target,
and forcing it into the same 3 ATR box as a marginal signal both stops it out
early and caps it short.

Premise first.  Before testing any book, measure whether |net| predicts the size
of the move at all: bucket bars by conviction decile and look at the forward
favourable and adverse close excursions over the holding horizon, in ATR units.
If the ratio does not rise with conviction the idea is dead and no backtest is
needed.

Then the variants, all on the honest bear-inclusive 12-month-lookback plan, with
the SELECTION HELD FIXED at the control geometry so that no variant gets a second
layer of search:

    stop^a   stop distance scaled by (cv/mean)^a, target follows at the same R
    targ^a   target scaled by (cv/mean)^a, stop unchanged
    both     both scaled
    be1      stop to breakeven once the trade is 1R in front
    trail    ATR trail once the trade is 1R / 2R in front

Widening the stop shrinks the size by the same factor, so risk per trade is
unchanged in every variant: this tests runway, not leverage.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
from strategies.s69_calsel import GRID, ctx, shape, daily, calmar_of
from strategies.s77_lookback import plan, stats

HOLD_TEST = 21


def premise():
    """Does conviction predict move size?  Forward excursions by conviction decile."""
    c = ctx(); g = c["g"]
    px = g.close.to_numpy(float); a = c["a"]
    u = shape(2.5)                      # the exponent the selection usually lands on
    n = len(px)
    mfe = np.full(n, np.nan); mae = np.full(n, np.nan)
    for i in range(n - HOLD_TEST - 1):
        if u[i] == 0.0: continue
        s = 1.0 if u[i] > 0 else -1.0
        e = px[i + 1]                                   # fill at next bar
        path = s * (px[i + 2: i + 2 + HOLD_TEST] - e) / a[i]
        if len(path) == 0: continue
        mfe[i] = path.max(); mae[i] = path.min()
    cv = np.abs(u)
    ok = ~np.isnan(mfe) & (cv > 0)
    d = pd.DataFrame(dict(cv=cv[ok], mfe=mfe[ok], mae=mae[ok]))
    d["bucket"] = pd.qcut(d.cv, 5, labels=False, duplicates="drop")
    print("does conviction predict the SIZE of the move?  (excursions in ATR, h=21 bars)\n")
    print(f"{'conviction quintile':>22}{'n':>7}{'mean cv':>9}{'MFE':>8}{'MAE':>8}{'MFE/|MAE|':>11}"
          f"{'mean fwd':>10}")
    for b, gg in d.groupby("bucket"):
        r = gg.mfe.mean() / max(abs(gg.mae.mean()), 1e-9)
        fwd = (gg.mfe + gg.mae).mean() / 2
        print(f"{'Q'+str(int(b)+1):>22}{len(gg):7d}{gg.cv.mean():9.2f}{gg.mfe.mean():8.2f}"
              f"{gg.mae.mean():8.2f}{r:11.3f}{fwd:10.3f}")
    print()


def sim_geom(cfg, start, end, risk, sa=0.0, ta=0.0, be=0.0, tr=0.0, trail_atr=0.0):
    p, stp, rr, hold = cfg
    c = ctx(); u = shape(p); a = c["a"]
    cv = np.abs(np.nan_to_num(u)); nz = cv > 0
    m = float(cv[nz].mean()) if nz.any() else 1.0
    k = np.where(nz, np.maximum(cv / max(m, 1e-12), 1e-6), 1.0)
    sd = stp * a * (k ** sa if sa else 1.0)
    td = stp * rr * a * (k ** ta if ta else 1.0) * (k ** sa if sa else 1.0)
    arr = dict(entry=np.nan_to_num(u), stop=sd, tp=td,
               exit=(cv <= 0.0).astype(float))
    if trail_atr > 0.0:
        arr["trail"] = trail_atr * a
    return backtest(c["g"], arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24, be_r=be, trail_after_r=tr)


def replay(p, risk, **kw):
    segs, pnl = [], []
    for s, e, cfg in p:
        m = sim_geom(cfg, s, e, risk, **kw); segs.append(daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))


VARIANTS = [
    ("control (uniform geometry)", {}),
    ("stop x cv^0.3",             dict(sa=0.3)),
    ("stop x cv^0.5",             dict(sa=0.5)),
    ("stop x cv^-0.3 (inverse)",  dict(sa=-0.3)),
    ("target x cv^0.3",           dict(ta=0.3)),
    ("target x cv^0.5",           dict(ta=0.5)),
    ("stop+target x cv^0.3",      dict(sa=0.3, ta=0.3)),
    ("breakeven after 1R",        dict(be=1.0)),
    ("breakeven after 1.5R",      dict(be=1.5)),
    ("trail 2 ATR after 1R",      dict(tr=1.0, trail_atr=2.0)),
    ("trail 3 ATR after 2R",      dict(tr=2.0, trail_atr=3.0)),
]

if __name__ == "__main__":
    premise()
    print("12-month lookback plan, selection held at control geometry, risk 8%\n")
    P12 = plan(12)
    for tag, kw in VARIANTS:
        r, pl = replay(P12, 0.08, **kw)
        stats(r, pl, tag, 0.08)
    print("\ndone: geometry sweep")
