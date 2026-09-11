"""
S15 - Convex Positioning Trend (CPT)   [BTCUSDT perp, single strategy]

Every earlier attempt used fixed-fractional risk and a fixed take-profit, which
produces a roughly symmetric return distribution - and a symmetric distribution
is exactly what makes drawdown scale linearly with size. This one deliberately
breaks that symmetry with three changes:

  1. NO take-profit. Winners are ridden out on an ATR trailing stop, so the right
     tail is unbounded while the left tail stays one stop wide.
  2. PYRAMIDING. Up to N extra units are added as the trade advances, each after
     a further step of R, and the stop is pulled to the new average entry so the
     enlarged package is never risking more than the original unit.
  3. HIGH-WATER-MARK THROTTLE. Nominal risk is full while the equity drawdown is
     shallower than dd_soft and tapers linearly to dd_floor of nominal at
     dd_hard. Drawdown becomes bounded by construction rather than by luck,
     which is what lets the base risk be set far higher than 1%.

Entry stack (all on closed 4h bars): the smart-money-vs-retail positioning
composite that scored the highest IC in the study, gated by trend agreement.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel
from research.runner import evaluate, line
import strategies.s07_smart as s07

def arrays(f, thr=0.7, stop_atr=2.5, trail_atr=3.0, trend=True, allow_short=True,
           comp=None):
    a = f.atr14.to_numpy()
    c = f.close.to_numpy()
    if comp is None:
        comp = s07.composite(f)
    up = c > f.ema_s.to_numpy()
    lng = comp > thr
    sht = (comp < -thr) & allow_short
    if trend:
        lng = lng & up
        sht = sht & (~up)
    e = np.where(lng, 1.0, np.where(sht, -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=stop_atr * a,
                tp=np.full(len(f), np.nan),          # no take-profit: ride it
                trail=trail_atr * a, exit=np.zeros(len(f)))

if __name__ == "__main__":
    fut, f = panel("4h")
    f = f[f.dt >= "2021-01-03"].reset_index(drop=True)
    comp = s07.composite(f)
    print("S15 Convex Positioning Trend — BTCUSDT perp, 4h signal / 15m execution")
    print(f"{'variant':<44}{'CAGR':>9}{'DD':>8}{'PF':>6}{'N':>6}{'WR':>6}{'Shp':>6}{'Clm':>7}"
          f"   {'OOS CAGR':>9}{'OOS DD':>8}")
    for pyr in (0, 3, 6):
        for risk in (0.02, 0.05, 0.10):
            for thr_dd in ((1.0, 1.0, 0.0), (0.06, 0.20, 0.0), (0.08, 0.22, 0.15)):
                ds, dh, df_ = thr_dd
                a = arrays(f, comp=comp, trail_atr=3.0)
                r = evaluate("x", f, a, "4h", verbose=False, risk=risk, max_lev=10.0,
                             since="2021-01-03", trail_after_r=1.0,
                             pyramid=pyr, pyramid_step=1.0,
                             dd_soft=ds, dd_hard=dh, dd_floor=df_)
                m = r["ALL"]; o = r["OOS"]
                tl = "off" if ds >= 1.0 else f"{int(ds*100)}/{int(dh*100)}"
                print(f"pyr{pyr} risk{int(risk*100):>2}% throttle{tl:<7}{'':<12}"
                      f"{m['cagr']*100:8.1f}%{m['max_dd']*100:7.1f}%{m['profit_factor']:6.2f}"
                      f"{m['trades']:6d}{m['win_rate']*100:5.1f}%{m['sharpe']:6.2f}{m['calmar']:7.2f}"
                      f"   {o['cagr']*100:8.1f}%{o['max_dd']*100:7.1f}%")
