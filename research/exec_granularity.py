"""
Does the 15-minute execution grid flatter the results?

Stops and targets were resolved on 15m bars, with the stop assumed to fill first
whenever one bar straddled both levels. A finer grid resolves the actual path
more faithfully: fewer bars straddle both levels, so the worst-case assumption
fires less often - but stops also trigger on wicks a coarse bar would have
smoothed over. This re-runs the finalists on a 1-MINUTE execution grid
(3,506,400 bars, zero gaps) to measure which way the bias ran.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
import research.harness as H
from research.harness import panel, backtest, IS_END, OOS_END
import strategies.s07_smart as s07
import strategies.s15_convex as s15
import strategies.s04_advol as s04

START = "2021-01-03"
fut, f4 = panel("4h")
fm = f4[f4.dt >= START].reset_index(drop=True)
comp = s07.composite(fm)

BOOKS = [
    ("S7 SMRD 2.5%", fm, lambda: s07.arrays(fm, comp, thr=0.7, atr_stop=3.5, rr=2.5),
     dict(risk=0.025, max_lev=10.0, max_bars_h=10*24), START),
    ("S15 convex 2% pyr3", fm, lambda: s15.arrays(fm, comp=comp, trail_atr=3.0, stop_atr=2.5),
     dict(risk=0.02, max_lev=10.0, trail_after_r=1.0, pyramid=3, pyramid_step=1.0), START),
    ("S4 AVT 2.5%", f4, lambda: s04.arrays(f4, dc_n=40, adx_min=20, er_min=0.30, vol_adapt=False),
     dict(risk=0.025, max_lev=10.0, trail_after_r=1.0), START),
]

print(f"{'book':<22}{'exec':>8}{'CAGR':>9}{'MaxDD':>9}{'PF':>7}{'N':>6}{'WR':>7}{'Shp':>7}")
for name, df, mk, kw, since in BOOKS:
    row = {}
    for grid in ("fut_15m", "fut_1m"):
        H.EXEC_TF[0] = grid
        m = backtest(df, mk(), "4h", start=since, end=OOS_END, **kw)
        row[grid] = m
        print(f"{name if grid=='fut_15m' else '':<22}{grid.replace('fut_',''):>8}"
              f"{m['cagr']*100:8.1f}%{m['max_dd']*100:8.1f}%{m['profit_factor']:7.2f}"
              f"{m['trades']:6d}{m['win_rate']*100:6.1f}%{m['sharpe']:7.2f}")
    a, b = row["fut_15m"], row["fut_1m"]
    print(f"{'':<22}{'delta':>8}{(b['cagr']-a['cagr'])*100:+8.1f}pp"
          f"{(b['max_dd']-a['max_dd'])*100:+8.1f}pp{b['profit_factor']-a['profit_factor']:+7.2f}"
          f"{b['trades']-a['trades']:+6d}{(b['win_rate']-a['win_rate'])*100:+6.1f}pp\n")
H.EXEC_TF[0] = "fut_15m"
