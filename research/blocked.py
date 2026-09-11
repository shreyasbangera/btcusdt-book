import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from strategies.s69_calsel import ctx, shape, sim

c = ctx(); u = shape(2.5); cv = np.abs(np.nan_to_num(u)); sg = np.sign(np.nan_to_num(u))
dt = pd.to_datetime(c["g"].dt).dt.tz_convert("UTC")
m = sim((2.5, 3.0, 2.0, 21), "2022-03-01", "2026-09-01", 0.08)
td = m["trades_df"].copy()
td["entry_dt"] = pd.to_datetime(td["entry_dt"], utc=True)
td["exit_dt"]  = pd.to_datetime(td["exit_dt"], utc=True)

pos = dt.searchsorted(td["entry_dt"].to_numpy())
end = dt.searchsorted(td["exit_dt"].to_numpy())
rows = []
for k in range(len(td)):
    i0, i1 = int(pos[k]), int(end[k])
    i0 = max(i0 - 1, 0)                       # signal bar is the one before the fill
    if i1 <= i0: continue
    side = 1 if td["side"].iloc[k] > 0 else -1
    seg = cv[i0:i1] * (sg[i0:i1] == side)     # same-sign conviction while held
    rows.append((cv[i0], float(seg.max()), float(seg.mean()), td["pnl"].iloc[k]))
d = pd.DataFrame(rows, columns=["cv0", "cvmax", "cvmean", "pnl"])
d = d[d.cv0 > 0]
d["ratio"] = d.cvmax / d.cv0
print(f"n trades with a conviction path: {len(d)}")
print(f"  conviction at entry:   mean {d.cv0.mean():.3f}  median {d.cv0.median():.3f}")
print(f"  peak same-sign during: mean {d.cvmax.mean():.3f}  median {d.cvmax.median():.3f}")
print(f"  peak / entry ratio:    median {d.ratio.median():.2f}  "
      f"p75 {d.ratio.quantile(.75):.2f}  p90 {d.ratio.quantile(.90):.2f}")
for thr in (1.5, 2.0, 3.0, 5.0):
    s = d[d.ratio >= thr]
    print(f"  trades whose conviction later rose >= {thr:>3.1f}x:  {len(s):4d} "
          f"({len(s)/len(d)*100:4.1f}%)   mean pnl {s.pnl.mean():8.1f} "
          f"vs {d[d.ratio < thr].pnl.mean():8.1f} for the rest")
print()
print("  entry-conviction quintile -> mean pnl, mean peak ratio")
d["q"] = pd.qcut(d.cv0, 5, labels=False, duplicates="drop")
for q, g in d.groupby("q"):
    print(f"    Q{int(q)+1}  n {len(g):4d}  cv0 {g.cv0.mean():6.3f}  "
          f"peak {g.cvmax.mean():6.3f}  ratio {g.ratio.median():5.2f}  "
          f"mean pnl {g.pnl.mean():9.1f}  total {g.pnl.sum():11.0f}")
