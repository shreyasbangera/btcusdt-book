"""
S18 - Growth-optimal leverage curve.

Compounded return is not monotone in position size. Below the growth-optimal
(Kelly) point more size buys more CAGR; above it, volatility drag and stop-outs
mean more size buys LESS CAGR and strictly more drawdown. This traces the curve
for the best BTCUSDT books so the ceiling is a measured quantity rather than an
assumption.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_START, IS_END, OOS_END
import strategies.s07_smart as s07
import strategies.s15_convex as s15
import strategies.s04_advol as s04

fut, f4 = panel("4h")
fm = f4[f4.dt >= "2021-01-03"].reset_index(drop=True)
comp = s07.composite(fm)

BOOKS = {
    "S15 convex trend (pyr 3)":
        (fm, lambda: s15.arrays(fm, comp=comp, trail_atr=3.0, stop_atr=2.5),
         dict(trail_after_r=1.0, pyramid=3, pyramid_step=1.0), "2021-01-03"),
    "S15 convex trend (pyr 0)":
        (fm, lambda: s15.arrays(fm, comp=comp, trail_atr=3.0, stop_atr=2.5),
         dict(trail_after_r=1.0), "2021-01-03"),
    "S4 adaptive trend":
        (f4, lambda: s04.arrays(f4, dc_n=40, adx_min=20, er_min=0.30, vol_adapt=False),
         dict(trail_after_r=1.0), IS_START),
}

RISKS = [0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.09, 0.12, 0.16, 0.22, 0.30]
for name, (df, mk, kw, since) in BOOKS.items():
    print(f"\n=== {name} — full period ===")
    print(f"{'risk/trade':>11}{'CAGR':>9}{'MaxDD':>9}{'PF':>7}{'N':>6}{'Calmar':>8}   growth")
    best = (-9, None)
    for r in RISKS:
        m = backtest(df, mk(), "4h", start=since, end=OOS_END, risk=r, max_lev=10.0, **kw)
        if m["cagr"] > best[0]:
            best = (m["cagr"], r)
        bar = "#" * max(0, int(m["cagr"] * 60)) if m["cagr"] > 0 else ""
        print(f"{r*100:10.1f}%{m['cagr']*100:8.1f}%{m['max_dd']*100:8.1f}%{m['profit_factor']:7.2f}"
              f"{m['trades']:6d}{m['calmar']:8.2f}   {bar}")
    print(f"  growth-optimal risk ≈ {best[1]*100:.1f}% / trade, peak CAGR {best[0]*100:.1f}%")
