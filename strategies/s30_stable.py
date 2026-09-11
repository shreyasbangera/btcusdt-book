"""
S30 - Stability-Screened Composite (SSC)   [BTCUSDT perp only]

Built from a different selection rule than everything before it. Rather than
ranking features by in-sample IC and building on the winner, every feature in
the 91-column panel was scored by measuring the SAME IC separately in-sample and
out-of-sample, and only those that keep their sign at both horizons AND retain
more than 40% of their strength were admitted.

That screen rejects `tt_vs_retail`, the feature the study's previous best book
was built on (IS +0.104 -> OOS -0.003), and admits three the study had not
built on:

    -oi_rank    open-interest percentile rank, faded. IS -0.137 / OOS -0.073 at
                h=96 - the strongest STABLE feature found. High open interest is
                crowded leverage, and crowded leverage is paid back.
    +ofi6_res   6-bar taker flow orthogonalised to past returns. OOS IC at h=24
                (+0.058) is HIGHER than in-sample (+0.039).
    -fund       funding rate, faded. Retention above 1.0 - stronger out of
                sample than in it.

The three come from different sources - positioning, flow and financing - so
they are close to independent.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.runner import evaluate, line, zs

START = "2021-01-03"

def composite(f, w=(1.0, 1.0, 1.0), zwin=480):
    parts = np.column_stack([
        -zs(f.oi_rank.to_numpy(float), zwin) * w[0],
         zs(f.ofi6_res.to_numpy(float), zwin) * w[1],
        -zs(f.fund.to_numpy(float), zwin) * w[2]])
    return np.nansum(np.clip(parts, -3, 3), axis=1) / np.sum(w)

def arrays(f, s, thr=0.7, atr_stop=3.5, rr=2.5, long_only=False):
    a = f.atr14.to_numpy()
    e = np.where(s > thr, 1.0, 0.0) if long_only else \
        np.where(s > thr, 1.0, np.where(s < -thr, -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=atr_stop * a,
                tp=atr_stop * rr * a, exit=np.zeros(len(f)))

if __name__ == "__main__":
    for tf in ("4h", "12h"):
        fut, f = panel(tf)
        f = f[f.dt >= START].reset_index(drop=True)
        print(f"\n===== S30 SSC {tf} =====")
        # each component alone, then the composite
        singles = {
            "-oi_rank":  -zs(f.oi_rank.to_numpy(float), 480),
            "ofi6_res":   zs(f.ofi6_res.to_numpy(float), 480),
            "-fund":     -zs(f.fund.to_numpy(float), 480),
            "COMPOSITE":  composite(f),
        }
        for nm, s in singles.items():
            for thr, hold_d in ((0.7, 5), (0.7, 10), (1.0, 10)):
                a = arrays(f, s, thr=thr, atr_stop=3.5, rr=2.5)
                r = evaluate("x", f, a, tf, verbose=False, risk=0.025, max_lev=10.0,
                             max_bars_h=hold_d * 24, since=START)
                m = r["ALL"]
                if m["trades"] < 80: continue
                print("  " + line(f"{nm} thr{thr} {hold_d}d [ALL]", m) +
                      f" | IS {r['IS']['cagr']*100:6.1f}% OOS {r['OOS']['cagr']*100:6.1f}% "
                      f"PF{r['OOS']['profit_factor']:5.2f} N{r['OOS']['trades']:4d}")
