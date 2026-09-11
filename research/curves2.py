"""Equity curves for the futures-only finalists."""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
import strategies.s07_smart as s07
import strategies.s15_convex as s15
import strategies.s04_advol as s04
import strategies.s20_continuous as s20
from strategies.s19_futonly import sleeves, combine
from engine.weights import simulate
from engine.data import load

START = "2021-01-03"
fut, f4 = panel("4h")
fm = f4[f4.dt >= START].reset_index(drop=True)
comp = s07.composite(fm)
cur = {}

m = backtest(fm, s07.arrays(fm, comp, thr=0.7, atr_stop=3.5, rr=2.5), "4h",
             start=START, end=OOS_END, risk=0.025, max_lev=10.0, max_bars_h=10*24)
cur["SMRD"] = pd.Series(m["equity"], index=pd.to_datetime(m["dt"]))
print(f"SMRD 2.5%   CAGR {m['cagr']*100:6.1f}%  DD {m['max_dd']*100:6.1f}%  PF {m['profit_factor']:.2f}  N {m['trades']}")

m = backtest(fm, s15.arrays(fm, comp=comp, trail_atr=3.0, stop_atr=2.5), "4h",
             start=START, end=OOS_END, risk=0.02, max_lev=10.0, trail_after_r=1.0,
             pyramid=3, pyramid_step=1.0)
cur["CONVEX"] = pd.Series(m["equity"], index=pd.to_datetime(m["dt"]))
print(f"CONVEX 2%   CAGR {m['cagr']*100:6.1f}%  DD {m['max_dd']*100:6.1f}%  PF {m['profit_factor']:.2f}  N {m['trades']}")

m = backtest(f4, s04.arrays(f4, dc_n=40, adx_min=20, er_min=0.30, vol_adapt=False), "4h",
             start=START, end=OOS_END, risk=0.025, max_lev=10.0, trail_after_r=1.0)
cur["AVT"] = pd.Series(m["equity"], index=pd.to_datetime(m["dt"]))
print(f"AVT 2.5%    CAGR {m['cagr']*100:6.1f}%  DD {m['max_dd']*100:6.1f}%  PF {m['profit_factor']:.2f}  N {m['trades']}")

p = combine(sleeves(2, START, OOS_END))
cur["PORT"] = pd.Series(p["equity"], index=pd.to_datetime(p["index"]))
print(f"PORTFOLIO   CAGR {p['cagr']*100:6.1f}%  DD {p['max_dd']*100:6.1f}%  PF {p['pf']:.2f}  N {p['trades']}  Shp {p['sharpe']:.2f}")

w = s20.weights(fm, comp, scale=1.4, target_vol=0.35, gross=1.0, deadband=0.0, cap=5.0)
sub, msk = s20.slice_(fut, fm, START, OOS_END)
r = simulate(sub, w[msk], max_w=5.0)
cur["CONT"] = pd.Series(r["equity"], index=pd.to_datetime(sub.dt))
print(f"CONTINUOUS  CAGR {r['cagr']*100:6.1f}%  DD {r['max_dd']*100:6.1f}%  PF {r['profit_factor']:.2f}  Shp {r['sharpe']:.2f}")

perp = load("fut_1h")
perp = perp[(perp.dt >= START) & (perp.dt < OOS_END)]
b = perp.set_index("dt").close
cur["PERP"] = 10_000.0 * b / b.iloc[0]
df = pd.DataFrame(cur)
df.to_parquet("results/curves2.parquet")
print("\nfinal equity:", {k: int(v.dropna().iloc[-1]) for k, v in cur.items()})
