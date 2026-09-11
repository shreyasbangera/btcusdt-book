"""
S22 - Short-timeframe positioning book  [BTCUSDT perp only]

The multi-timeframe scan showed the positioning composite scoring its highest
in-sample Sharpe at 2h rather than the 4h used everywhere else. Shorter bars mean
more independent bets, which is the breadth term - but also more round turns.
This tests whether the 2h result survives out of sample and honest costs, and
where the frequency actually optimises.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s07_smart as s07

START = "2021-01-03"
print(f"{'tf':>4}{'thr':>6}{'hold':>6} | {'IS CAGR':>9}{'DD':>7}{'PF':>6}{'Shp':>6} | "
      f"{'OOS CAGR':>9}{'DD':>7}{'PF':>6}{'Shp':>6} | {'ALL CAGR':>9}{'DD':>7}{'PF':>6}"
      f"{'N':>6}{'Shp':>6}{'Clm':>6}")
for tf in ("1h", "2h", "3h", "6h"):
    fut, f = panel(tf)
    f = f[f.dt >= START].reset_index(drop=True)
    comp = s07.composite(f)
    hrs = int(tf[:-1])
    for thr in (0.5, 0.8, 1.1):
        for hold_d in (3, 7):
            a = s07.arrays(f, comp, thr=thr, atr_stop=3.5, rr=2.5)
            r = {}
            for lab, s, e in (("IS", START, IS_END), ("OOS", IS_END, OOS_END), ("ALL", START, OOS_END)):
                r[lab] = backtest(f, a, tf, start=s, end=e, risk=0.01, max_lev=10.0,
                                  max_bars_h=hold_d*24)
            i_, o, al = r["IS"], r["OOS"], r["ALL"]
            if al["trades"] < 100: continue
            print(f"{tf:>4}{thr:>6.1f}{hold_d:>5}d | {i_['cagr']*100:8.1f}%{i_['max_dd']*100:6.1f}%"
                  f"{i_['profit_factor']:6.2f}{i_['sharpe']:6.2f} | "
                  f"{o['cagr']*100:8.1f}%{o['max_dd']*100:6.1f}%{o['profit_factor']:6.2f}{o['sharpe']:6.2f} | "
                  f"{al['cagr']*100:8.1f}%{al['max_dd']*100:6.1f}%{al['profit_factor']:6.2f}"
                  f"{al['trades']:6d}{al['sharpe']:6.2f}{al['calmar']:6.2f}")
