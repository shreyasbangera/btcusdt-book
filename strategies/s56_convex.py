"""
S56 - The last structural lever: payoff shape.

Where the target can still come from, stated as arithmetic:

    CAGR at the drawdown limit  =  Calmar x 20%
    Calmar                      =  (Calmar/Sharpe) x Sharpe

Sharpe is capped near 3 by the correlation ceiling and sits at 2.20. The bet
count is closed - S55 showed sampling the signals faster destroys IC faster
than sqrt(N) gains. That leaves the RATIO, which is 1.67 here and is not a
constant: it is a property of the shape of the return distribution. A book
whose winners run and whose losers are cut has positive skew, shallower
drawdowns relative to its volatility, and a higher Calmar at the same Sharpe.

Four shapes, none of them tested on the net book before:

  TARGET     the current 2R take-profit                    (baseline)
  TRAIL      no take-profit at all; an ATR trailing stop that only tightens
  PYRAMID    add to the position while the signal strengthens, pulling the
             stop to the new average entry so the package never risks more
             than one unit
  CONVEX     trail + pyramid together

and one sizing change:

  QUADRATIC  size on |net|^2 rather than |net| - bet far harder on unanimity
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

def book(g, v, stp=3.0, rr=2.0, trail=0.0, flat=True):
    a = g.atr14.to_numpy(float)
    d = dict(entry=np.nan_to_num(v), stop=stp * a,
             tp=np.zeros(len(g)) if rr <= 0 else stp * rr * a,
             exit=(np.abs(np.nan_to_num(v)) <= 0.0).astype(float) if flat else np.zeros(len(g)))
    if trail > 0: d["trail"] = trail * a
    return d

def go(g, tag, v, risk, stp=3.0, rr=2.0, trail=0.0, pyr=0, pstep=1.0,
       trail_after=0.0, hold=21, quiet=False):
    kw = dict(risk=risk, max_lev=10.0, max_bars_h=hold * 24,
              pyramid=pyr, pyramid_step=pstep, trail_after_r=trail_after)
    arr = book(g, v, stp, rr, trail)
    A = backtest(g, arr, "12h", start=S.FULL_START, end=OOS_END, **kw)
    I = backtest(g, arr, "12h", start=S.FULL_START, end=IS_END, **kw)
    O = backtest(g, arr, "12h", start=IS_END, end=OOS_END, **kw)
    r = pd.Series(A["equity"], index=pd.to_datetime(A["dt"])).resample("1D").last(
        ).dropna().pct_change().fillna(0).to_numpy()
    b = bootstrap_dd(r, n=2000)
    ratio = A["calmar"] / A["sharpe"] if A["sharpe"] > 0 else 0.0
    print(f"{tag:>28}{risk*100:5.0f}% | {A['cagr']*100:7.1f}%{A['max_dd']*100:7.1f}%"
          f"{A['profit_factor']:6.2f}{A['trades']:6d}{A['win_rate']*100:5.1f}%{A['sharpe']:6.2f}"
          f"{A['calmar']:6.2f}{ratio:6.2f} | {I['cagr']*100:6.1f}%{O['cagr']*100:7.1f}%"
          f"{O['profit_factor']:5.2f} | {b['dd_median']*100:6.1f}%{b['p_dd_worse_than_20']*100:5.0f}%")
    return A

if __name__ == "__main__":
    g = S.grid(S.FULL_START)
    v = S.composite(g, S46.LONG)
    v2 = np.sign(v) * np.minimum(np.abs(v) ** 2 * 1.6, 2.0)     # quadratic conviction
    print(f"{'shape':>28}{'risk':>6} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'WR':>6}{'Shp':>6}"
          f"{'Clm':>6}{'C/S':>6} | {'IS':>6}{'OOS':>7}{'OOSPF':>5} | {'medDD':>7}{'P>20%':>5}")
    for risk in (0.08, 0.10):
        go(g, "TARGET 2R (baseline)", v, risk)
    for risk in (0.06, 0.08, 0.10):
        go(g, "TRAIL 3 ATR, no target", v, risk, rr=0, trail=3.0, trail_after=1.0)
    for risk in (0.06, 0.08):
        go(g, "TRAIL 2 ATR, no target", v, risk, rr=0, trail=2.0, trail_after=1.0)
    for risk in (0.06, 0.08):
        go(g, "PYRAMID 3 + target 2R", v, risk, pyr=3, pstep=1.0)
    for risk in (0.05, 0.06, 0.08):
        go(g, "CONVEX trail+pyramid", v, risk, rr=0, trail=3.0, trail_after=1.0, pyr=3, pstep=1.0)
    for risk in (0.06, 0.08):
        go(g, "QUADRATIC conviction", v2, risk)
    for risk in (0.06, 0.08):
        go(g, "QUADRATIC + convex", v2, risk, rr=0, trail=3.0, trail_after=1.0, pyr=3, pstep=1.0)
