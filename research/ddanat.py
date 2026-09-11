"""Anatomy of the drawdowns: are they one event or a structural shape?

If the -15% max drawdown is a single week, then every Calmar improvement measured
against it is an improvement against one observation and cannot be trusted.  If
the top drawdowns are many and similar, the shape is real and worth attacking.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from strategies.s77_lookback import plan, replay

P12 = plan(12)
r, pl = replay(P12, 0.08)
e = pd.Series(np.cumprod(1 + r.to_numpy()), index=r.index)
peak = e.cummax(); dd = e / peak - 1

# segment into distinct drawdown episodes (peak -> trough -> recovery)
epi, start, trough, tval = [], None, None, 0.0
for t, v in dd.items():
    if v < 0 and start is None:
        start, trough, tval = t, t, v
    elif v < 0:
        if v < tval: tval, trough = v, t
    elif start is not None:
        epi.append((start, trough, t, tval)); start = None
if start is not None:
    epi.append((start, trough, dd.index[-1], tval))
epi.sort(key=lambda x: x[3])

print(f"{len(epi)} distinct drawdown episodes over {(r.index[-1]-r.index[0]).days/365.25:.1f} years\n")
print(f"{'rank':>4}{'peak':>13}{'trough':>13}{'recovered':>13}{'depth':>9}{'days down':>11}{'days back':>11}")
for k, (a, b, c, v) in enumerate(epi[:10]):
    print(f"{k+1:>4}{str(a.date()):>13}{str(b.date()):>13}{str(c.date()):>13}"
          f"{v*100:8.1f}%{(b-a).days:11d}{(c-b).days:11d}")
d = np.array([x[3] for x in epi])
print(f"\ndeepest {d[0]*100:.1f}%   2nd {d[1]*100:.1f}%   3rd {d[2]*100:.1f}%   "
      f"5th {d[4]*100:.1f}%   10th {d[9]*100:.1f}%")
print(f"episodes deeper than 10%: {(d < -0.10).sum()}   deeper than 5%: {(d < -0.05).sum()}")
print(f"time in drawdown: {(dd < -0.01).mean()*100:.0f}% of days")
print("\nworst 10 single days: " + " ".join(f"{x*100:.1f}%" for x in np.sort(r.to_numpy())[:10]))
print(f"daily vol {r.std()*100:.2f}%   skew {pd.Series(r).skew():.2f}   "
      f"kurtosis {pd.Series(r).kurtosis():.1f}")
print("done: dd anatomy")
