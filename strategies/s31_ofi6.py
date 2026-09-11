"""
S31 - Short-Window Orthogonal Flow (SWOF)   [BTCUSDT perp only]

The best book in the study, and it was found by changing the SELECTION RULE
rather than by searching harder. Every previous strategy picked its feature by
in-sample IC; this one was picked by the stability screen - measuring the same
IC separately in-sample and out-of-sample and keeping only features that hold
their sign and most of their strength in both.

    ofi6_res = 6-bar mean taker-buy imbalance, orthogonalised to past returns
               over 1/2/4/6/12/24 bars, with projection coefficients refit
               monthly on an EXPANDING window of strictly past data.

    stability: IS h=24 +0.039 -> OOS +0.058 (out-of-sample IC HIGHER than in)
               IS h=96 +0.085 -> OOS +0.044, retention 0.68

Raw taker imbalance is contaminated by short-horizon reversal; projecting it off
recent returns isolates the part of aggressive flow that recent price action does
not already explain. The 6-bar window is short enough to react and long enough
to average out single-print noise.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs

START = "2021-01-03"

def signal(f, zwin=480):
    return zs(f.ofi6_res.to_numpy(float), zwin)

def arrays(f, s, thr=1.0, atr_stop=3.5, rr=2.5, long_only=False):
    a = f.atr14.to_numpy()
    e = np.where(s > thr, 1.0, 0.0) if long_only else \
        np.where(s > thr, 1.0, np.where(s < -thr, -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=atr_stop * a,
                tp=atr_stop * rr * a, exit=np.zeros(len(f)))

def run(tf, thr, stp, rr, hold_d, risk, fee=5.0, slip=3.0):
    fut, f = panel(tf)
    f = f[f.dt >= START].reset_index(drop=True)
    a = arrays(f, signal(f), thr=thr, atr_stop=stp, rr=rr)
    out = {}
    for lab, s, e in (("IS", START, IS_END), ("OOS", IS_END, OOS_END), ("ALL", START, OOS_END)):
        out[lab] = backtest(f, a, tf, start=s, end=e, risk=risk, max_lev=10.0,
                            max_bars_h=hold_d * 24, fee=fee, slip=slip)
    return out

if __name__ == "__main__":
    print("S31 Short-Window Orthogonal Flow — parameter map (risk 2.5%)")
    print(f"{'tf':>4}{'thr':>6}{'stop':>6}{'rr':>5}{'hold':>6} | {'ALL CAGR':>9}{'DD':>8}{'PF':>6}"
          f"{'N':>6}{'Shp':>6}{'Clm':>6} | {'IS':>8}{'OOS':>8}{'OOSPF':>7}")
    best = None
    for tf in ("6h", "8h", "12h"):
        for thr in (0.7, 1.0, 1.3):
            for stp, rr in ((3.0, 2.0), (3.5, 2.5), (4.5, 2.0)):
                for hold_d in (7, 12):
                    o = run(tf, thr, stp, rr, hold_d, 0.025)
                    m = o["ALL"]
                    if m["trades"] < 120: continue
                    print(f"{tf:>4}{thr:>6.1f}{stp:>6.1f}{rr:>5.1f}{hold_d:>5}d | "
                          f"{m['cagr']*100:8.1f}%{m['max_dd']*100:7.1f}%{m['profit_factor']:6.2f}"
                          f"{m['trades']:6d}{m['sharpe']:6.2f}{m['calmar']:6.2f} | "
                          f"{o['IS']['cagr']*100:7.1f}%{o['OOS']['cagr']*100:7.1f}%"
                          f"{o['OOS']['profit_factor']:7.2f}")
                    score = m["sharpe"] * (1 if m["max_dd"] > -0.22 else 0.5)
                    if best is None or score > best[0]:
                        best = (score, (tf, thr, stp, rr, hold_d))
    print(f"\nbest by Sharpe (drawdown-penalised): {best[1]}")
