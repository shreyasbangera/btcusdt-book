"""
S2 - Crowding-Reversal Ensemble (CRE)

Four low-correlation positioning/flow signals are z-scored and averaged:
    -funding_z   (levered crowding, contrarian)
    -basis_z     (perp premium/discount vs spot, contrarian)
    +ofi24_res   (spot taker flow orthogonal to recent returns)
    +ofi96_res   (slower version of the same)
Trade the tails of the composite; exit on time or ATR stop/target.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel
from research.runner import evaluate, zs, line

def composite(f, zwin=480):
    parts = np.column_stack([
        -zs(f.fund.to_numpy(), zwin),
        -zs(f.basis.to_numpy(), zwin),
         zs(f.ofi24_res.to_numpy(), zwin),
         zs(f.ofi96_res.to_numpy(), zwin)])
    return np.nanmean(np.clip(parts, -3, 3), axis=1)

def arrays(f, comp, thr=1.0, atr_stop=2.5, rr=2.0, long_only=False, short_thr=None):
    a = f.atr14.to_numpy()
    st = short_thr if short_thr is not None else thr
    e = np.where(comp > thr, 1.0, np.where((comp < -st) & (not long_only), -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=atr_stop * a,
                tp=atr_stop * rr * a, exit=np.zeros(len(f)))

if __name__ == "__main__":
    for tf in ("4h", "6h", "12h"):
        fut, f = panel(tf)
        comp = composite(f)
        h = int(tf[:-1])
        print(f"\n===== {tf} bars =====")
        for thr in (0.5, 0.8, 1.1):
            for hold_d, st, rr in ((2, 2.0, 1.5), (4, 2.5, 2.0), (7, 3.0, 2.0)):
                a = arrays(f, comp, thr=thr, atr_stop=st, rr=rr)
                r = evaluate(f"thr{thr} hold{hold_d}d stop{st}", f, a, tf, verbose=False,
                             risk=0.01, max_lev=5.0, max_bars_h=hold_d * 24)
                print("  " + line(f"thr{thr} hold{hold_d}d {st}x{rr} [ALL]", r["ALL"]) +
                      f"  | OOS CAGR{r['OOS']['cagr']*100:7.1f}% PF{r['OOS']['profit_factor']:5.2f}")
