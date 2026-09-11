"""
S1 - Positioning-Reversal with Flow Confirmation (PRFC)

Thesis (from Order-Flow & crypto-basis literature):
  The perpetual basis and funding rate measure how crowded LEVERAGED positioning
  is.  Spot taker order flow, once orthogonalised to recent returns, measures
  what unlevered flow is actually doing.  When the two DISAGREE - derivatives
  crowded short while spot flow is accumulating (or vice versa) - the derivative
  crowd is usually the side that gets squeezed.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, report

def signals(f, b_lo=-1.2, b_hi=1.8, flow_thr=0.0, atr_stop=2.0, rr=1.75,
            max_days=7, use_flow=True):
    n = len(f)
    bz  = f.basis_z.to_numpy()
    flz = f.ofi24_resz.to_numpy()
    a   = f.atr14.to_numpy()
    long_ok  = (bz < b_lo)
    short_ok = (bz > b_hi)
    if use_flow:
        long_ok  &= (flz > flow_thr)
        short_ok &= (flz < -flow_thr)
    entry = np.where(long_ok, 1.0, np.where(short_ok, -1.0, 0.0))
    entry = np.nan_to_num(entry)
    stop = atr_stop * a
    tp   = atr_stop * rr * a
    return dict(entry=entry, stop=stop, tp=tp, exit=np.zeros(n))

if __name__ == "__main__":
    for tf in ("4h", "1h"):
        fut, f = panel(tf)
        h = int(tf[:-1])
        for use_flow in (False, True):
            a = signals(f, use_flow=use_flow)
            a["exit"] = np.zeros(len(f))
            report(f"S1 PRFC {tf} flow={use_flow}", f, a, tf,
                   risk=0.01, max_lev=5.0, max_bars_h=7*24)
