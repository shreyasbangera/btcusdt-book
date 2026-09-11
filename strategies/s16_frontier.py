"""
S16 - Drawdown-constrained optimisation of the convex trend book.

Grid over base risk, pyramid depth and the three throttle parameters. Selection
is done on the IN-SAMPLE window only, maximising CAGR subject to a max-drawdown
budget; the chosen configuration is then reported out-of-sample untouched.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd, itertools, json
from research.harness import panel, backtest, IS_START, IS_END, OOS_END
import strategies.s07_smart as s07
import strategies.s15_convex as s15

fut, f = panel("4h")
f = f[f.dt >= "2021-01-03"].reset_index(drop=True)
comp = s07.composite(f)

GRID = dict(
    risk=[0.02, 0.04, 0.06, 0.09, 0.13],
    pyramid=[0, 2, 4, 8],
    dd=[(1.0, 1.0, 0.0),            # throttle off
        (0.05, 0.16, 0.25), (0.05, 0.16, 0.40),
        (0.07, 0.18, 0.25), (0.07, 0.18, 0.40),
        (0.10, 0.20, 0.30), (0.10, 0.22, 0.45),
        (0.04, 0.14, 0.35)],
    trail=[2.0, 3.0, 4.5],
)

rows = []
for risk, pyr, (ds, dh, dfl), tr in itertools.product(
        GRID["risk"], GRID["pyramid"], GRID["dd"], GRID["trail"]):
    a = s15.arrays(f, comp=comp, trail_atr=tr, stop_atr=2.5)
    m = backtest(f, a, "4h", start="2021-01-03", end=IS_END, risk=risk, max_lev=10.0,
                 trail_after_r=1.0, pyramid=pyr, pyramid_step=1.0,
                 dd_soft=ds, dd_hard=dh, dd_floor=dfl)
    rows.append(dict(risk=risk, pyr=pyr, ds=ds, dh=dh, dfl=dfl, trail=tr,
                     cagr=m["cagr"], dd=m["max_dd"], pf=m["profit_factor"],
                     n=m["trades"], shp=m["sharpe"], clm=m["calmar"]))
R = pd.DataFrame(rows)
R.to_parquet(str(_P.RESULTS / "s16_grid.parquet"))
print(f"grid size {len(R)}  (in-sample 2021-01 → 2024-06)")

for budget in (0.15, 0.20, 0.25, 0.30, 0.40):
    ok = R[(R.dd > -budget) & (R.n >= 60)]
    if not len(ok):
        print(f"\nDD budget {budget*100:.0f}%: no configuration"); continue
    b = ok.sort_values("cagr", ascending=False).iloc[0]
    print(f"\nDD budget {budget*100:>3.0f}% -> best IS CAGR {b.cagr*100:6.1f}%  DD {b.dd*100:6.1f}%  "
          f"PF {b.pf:.2f}  N {int(b.n)}  Calmar {b.clm:.2f}")
    print(f"     risk {b.risk*100:.0f}%  pyr {int(b.pyr)}  trail {b.trail}xATR  "
          f"throttle soft {b.ds*100:.0f}% hard {b.dh*100:.0f}% floor {b.dfl:.2f}")
    a = s15.arrays(f, comp=comp, trail_atr=b.trail, stop_atr=2.5)
    kw = dict(risk=b.risk, max_lev=10.0, trail_after_r=1.0, pyramid=int(b.pyr),
              pyramid_step=1.0, dd_soft=b.ds, dd_hard=b.dh, dd_floor=b.dfl)
    o = backtest(f, a, "4h", start=IS_END, end=OOS_END, **kw)
    al = backtest(f, a, "4h", start="2021-01-03", end=OOS_END, **kw)
    print(f"     OOS  CAGR {o['cagr']*100:6.1f}%  DD {o['max_dd']*100:6.1f}%  PF {o['profit_factor']:.2f}  N {o['trades']}")
    print(f"     FULL CAGR {al['cagr']*100:6.1f}%  DD {al['max_dd']*100:6.1f}%  PF {al['profit_factor']:.2f}  "
          f"N {al['trades']}  Sharpe {al['sharpe']:.2f}  Calmar {al['calmar']:.2f}")
