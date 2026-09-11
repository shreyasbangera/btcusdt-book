"""
S28 - Market-Wide Flow Breadth (MWFB)   [trades BTCUSDT perp only]

BTC's own taker imbalance is a noisy estimate of aggressive flow. Averaging the
same measure across 15 liquid USDⓈ-M perps estimates CRYPTO-WIDE aggression with
far less idiosyncratic noise - more breadth in the ESTIMATOR, not in the bets.
Only BTCUSDT is ever traded; the alts are used purely as sensors.

Screen (IS 2021-01 → 2024-06, 1h bars):
    flow_breadth96 = median over 15 perps of the 96h mean taker imbalance
        IC +0.062 at h=96 vs +0.039 for BTC's own ofi24_z
        top decile +131.9 bps over 96h (t=10.9), +115.9 bps net of cost
        correlation with the S7 positioning composite: only 0.22

Blending it into the S7 composite DILUTED that signal (combined IC 0.070 vs
0.108 at h=96) - the same failure as S2 - so it is run as its own sleeve.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.runner import evaluate, line
from engine.indicators import zscore

START = "2021-01-03"

def signal(f, col="flow_breadth96", zwin=480):
    F = pd.read_parquet(str(_P.DATA / "breadth.parquet"))
    F = F.reindex(pd.to_datetime(f.dt)).reset_index(drop=True)
    return zscore(F[col].to_numpy(float), zwin)

def arrays(f, s, thr=0.7, sthr=None, atr_stop=3.5, rr=2.5, long_only=False):
    a = f.atr14.to_numpy()
    st = thr if sthr is None else sthr
    e = np.where(s > thr, 1.0, 0.0) if long_only else \
        np.where(s > thr, 1.0, np.where(s < -st, -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=atr_stop * a,
                tp=atr_stop * rr * a, exit=np.zeros(len(f)))

if __name__ == "__main__":
    for tf in ("4h", "12h"):
        fut, f = panel(tf)
        f = f[f.dt >= START].reset_index(drop=True)
        s = signal(f)
        print(f"\n===== S28 MWFB {tf} =====")
        for thr in (0.4, 0.7, 1.0):
            for hold_d, stp, rr in ((5, 3.0, 2.0), (10, 3.5, 2.5)):
                for lo in (False, True):
                    a = arrays(f, s, thr=thr, atr_stop=stp, rr=rr, long_only=lo)
                    r = evaluate("x", f, a, tf, verbose=False, risk=0.02, max_lev=10.0,
                                 max_bars_h=hold_d * 24, since=START)
                    if r["ALL"]["trades"] < 60: continue
                    print("  " + line(f"thr{thr} {hold_d}d L{int(lo)} [ALL]", r["ALL"]) +
                          f" | IS {r['IS']['cagr']*100:6.1f}% OOS {r['OOS']['cagr']*100:6.1f}% "
                          f"PF{r['OOS']['profit_factor']:5.2f}")
