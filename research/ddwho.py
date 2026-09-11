"""Who loses the money, and when?

The deepest drawdown of the whole record (-14.8%) runs 2024-10-17 to 2025-02-23
- 129 days of grind through what was the strongest trend in the sample.  A book
whose returns track trendiness at +0.61 losing its worst money inside the biggest
trend needs explaining.  Attribute the P&L of every trade to the signals that
were on when it was opened, inside and outside that window.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from strategies.s69_calsel import ctx, shape
from strategies.s77_lookback import plan, replay
from strategies.s83b_topup import sim_add
import strategies.s46_net as S46
import strategies.s45_single as S

c = ctx(); g = c["g"]; dt = pd.to_datetime(g.dt).dt.tz_convert("UTC")
NAMES = S46.SHORT
sig = {n: np.nan_to_num(g[f"s_{n}"].to_numpy(float)) for n in NAMES}
thr = S.THR

P12 = plan(12)
rows = []
for s, e, cfg in P12:
    m = sim_add(cfg, s, e, 0.08)
    td = m["trades_df"]
    if td is None or not len(td): continue
    td = td.copy()
    td["entry_dt"] = pd.to_datetime(td["entry_dt"], utc=True)
    ix = dt.searchsorted(td["entry_dt"].to_numpy()) - 1
    ix = np.clip(ix, 0, len(dt) - 1)
    for k in range(len(td)):
        i = int(ix[k]); side = 1 if td["side"].iloc[k] > 0 else -1
        r = dict(dt=dt.iloc[i], side=side, pnl=float(td["pnl"].iloc[k]),
                 reason=int(td["reason"].iloc[k]))
        for n in NAMES:
            z = sig[n][i]; t = thr[n]
            r[n] = (1 if z > t else (-1 if z < -t else 0))
        rows.append(r)
D = pd.DataFrame(rows).sort_values("dt").reset_index(drop=True)

W = (pd.Timestamp("2024-10-17", tz="UTC"), pd.Timestamp("2025-02-23", tz="UTC"))
inw = (D.dt >= W[0]) & (D.dt <= W[1])
print(f"trades {len(D)}   in the worst drawdown window {inw.sum()}\n")

for lab, sub in (("WORST DD 2024-10 -> 2025-02", D[inw]), ("everywhere else", D[~inw])):
    print(f"--- {lab}:  n {len(sub)}   total P&L {sub.pnl.sum():,.0f}   "
          f"mean {sub.pnl.mean():,.1f}   win {100*(sub.pnl>0).mean():.0f}%")
    print(f"{'':>10}{'long n':>8}{'long pnl':>11}{'short n':>9}{'short pnl':>12}")
    for sd, nm in ((1, "long"), (-1, "short")):
        s2 = sub[sub.side == sd]
        print(f"{nm:>10}{len(s2):8d}{s2.pnl.sum():11,.0f}")
    print(f"{'signal':>10}{'agree n':>9}{'agree pnl':>12}{'oppose n':>10}{'oppose pnl':>12}")
    for n in NAMES:
        a = sub[(sub[n] != 0) & (sub[n] == sub.side)]
        o = sub[(sub[n] != 0) & (sub[n] == -sub.side)]
        print(f"{n:>10}{len(a):9d}{a.pnl.sum():12,.0f}{len(o):10d}{o.pnl.sum():12,.0f}")
    print()
print("done: dd attribution")
