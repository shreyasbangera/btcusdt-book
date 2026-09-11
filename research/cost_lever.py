"""
How much of the wall is the 16 bps taker round-turn?

Every result in the study assumed taker execution (5 bps fee + 3 bps slippage per
side). Binance USDT-M *maker* fee is 1.8 bps, and a resting limit order that fills
has ~0 slippage by construction. This re-runs the finalists across a cost ladder
from taker down to maker, and re-tests the two signals that were killed at the
screen purely on cost grounds.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_START, IS_END, OOS_END
import strategies.s07_smart as s07
import strategies.s04_advol as s04

LADDER = [(5.0, 3.0, "taker  16 bps RT  (study baseline)"),
          (5.0, 1.0, "taker, tight slip  12 bps RT"),
          (1.8, 1.0, "maker  5.6 bps RT"),
          (1.8, 0.0, "maker, perfect fill  3.6 bps RT"),
          (0.0, 0.0, "zero cost (upper bound)")]

fut4, f4 = panel("4h")
f4m = f4[f4.dt >= "2021-01-03"].reset_index(drop=True)
comp = s07.composite(f4m)

print("=== Finalists across the cost ladder (full period) ===")
print(f"{'cost regime':<36}{'S7 SMRD CAGR':>14}{'PF':>7}   {'S4 AVT CAGR':>13}{'PF':>7}")
for fee, slip, lab in LADDER:
    a = s07.arrays(f4m, comp, thr=0.7, atr_stop=3.5, rr=2.5)
    m1 = backtest(f4m, a, "4h", start="2021-01-03", end=OOS_END, risk=0.01,
                  max_lev=10.0, max_bars_h=10*24, fee=fee, slip=slip)
    b = s04.arrays(f4, dc_n=40, adx_min=20, er_min=0.30, vol_adapt=False)
    m2 = backtest(f4, b, "4h", start=IS_START, end=OOS_END, risk=0.01,
                  max_lev=10.0, trail_after_r=1.0, fee=fee, slip=slip)
    print(f"{lab:<36}{m1['cagr']*100:13.1f}%{m1['profit_factor']:7.2f}   "
          f"{m2['cagr']*100:12.1f}%{m2['profit_factor']:7.2f}")

print("\n=== Signals killed at the screen: do cheaper fills revive them? ===")
from engine.data import load
from engine.indicators import rsi, atr
for tf, lab in (("15m", "15m sign reversal"), ("1h", "1h RSI(4) reversion")):
    d = load("fut_15m") if tf == "15m" else load("fut_1h")
    c = d.close.to_numpy(); h = d.high.to_numpy(); l = d.low.to_numpy()
    if tf == "15m":
        sig = -np.sign(np.r_[0, np.diff(np.log(c))])
    else:
        sig = -np.sign(rsi(c, 4) - 50)
    a14 = atr(h, l, c, 14)
    ent = np.nan_to_num(sig)
    print(f"\n  {lab}")
    print(f"  {'cost regime':<36}{'CAGR':>10}{'PF':>7}{'N':>8}{'Sharpe':>8}")
    for fee, slip, cl in LADDER:
        m = backtest(d, dict(entry=ent, stop=a14*2.0, tp=a14*2.0,
                             exit=np.zeros(len(d))), tf,
                     start=IS_START, end=OOS_END, risk=0.005, max_lev=5.0,
                     fee=fee, slip=slip) if tf == "15m" else None
        if m is None:
            eng_df = d
            m = backtest(eng_df, dict(entry=ent, stop=a14*2.0, tp=a14*2.0,
                                      exit=np.zeros(len(d))), tf,
                         start=IS_START, end=OOS_END, risk=0.005, max_lev=5.0,
                         fee=fee, slip=slip)
        print(f"  {cl:<36}{m['cagr']*100:9.1f}%{m['profit_factor']:7.2f}"
              f"{m['trades']:8d}{m['sharpe']:8.2f}")
