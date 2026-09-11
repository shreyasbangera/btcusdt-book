"""
S33 - Adding the open-interest sleeve   [BTCUSDT perp only]

S32 showed the gain comes from pairing reads that are genuinely different, not
from adding books. The stability screen surfaced a fourth read this study never
built a portfolio around: `oi_rank`, open-interest percentile, faded. It is the
strongest STABLE feature in the panel (IS -0.137 / OOS -0.073) but a weak book on
its own (8.1% CAGR, PF 1.13, -32% drawdown).

The question is whether a weak-but-different sleeve still earns a place. It reads
neither flow nor account positioning but the total size of the levered book, so
it may decorrelate from all three.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs
import strategies.s30_stable as s30
import strategies.s32_pair as s32

START = "2021-01-03"

def sleeves(k, s, e, use_oi=True):
    out = s32.sleeves(k, s, e, with_convex=True)
    if use_oi:
        f4 = s32.P("4h")
        sig = -zs(f4.oi_rank.to_numpy(float), 480)
        a = s30.arrays(f4, sig, thr=0.7, atr_stop=3.5, rr=2.5)
        m = backtest(f4, a, "4h", start=s, end=e, risk=min(0.020*k, 0.08),
                     max_lev=10.0, max_bars_h=10*24)
        out["OI"] = s32.daily(m); out["_OI_n"] = m["trades"]
    return out

if __name__ == "__main__":
    s1 = sleeves(1, START, IS_END)
    cols = [c for c in s1 if not c.startswith("_")]
    print("in-sample correlation with the OI sleeve added:")
    print(pd.DataFrame({c: s1[c] for c in cols}).corr().round(3).to_string())
    for use_oi in (True,):
        s1b = sleeves(1, START, IS_END, use_oi=use_oi)
        cc = [c for c in s1b if not c.startswith("_")]
        inv = {c: 1.0/max(s1b[c].std(), 1e-9) for c in cc}
        tot = sum(inv.values()); rp = {c: inv[c]/tot for c in cc}
        print(f"\nweights: " + "  ".join(f"{c} {rp[c]*100:.0f}%" for c in cc))
        print(f"{'knob':>5} | {'IS CAGR':>9}{'DD':>8} | {'OOS CAGR':>9}{'DD':>8} | "
              f"{'ALL CAGR':>9}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}{'N':>6}")
        for k in (1, 1.5, 2):
            r = {lab: s32.combine(sleeves(k, ss, ee, use_oi=use_oi), rp)
                 for lab, ss, ee in (("IS", START, IS_END), ("OOS", IS_END, OOS_END),
                                     ("ALL", START, OOS_END))}
            a = r["ALL"]
            print(f"{k:>5} | {r['IS']['cagr']*100:8.1f}%{r['IS']['max_dd']*100:7.1f}% | "
                  f"{r['OOS']['cagr']*100:8.1f}%{r['OOS']['max_dd']*100:7.1f}% | "
                  f"{a['cagr']*100:8.1f}%{a['max_dd']*100:7.1f}%{a['pf']:6.2f}{a['sharpe']:6.2f}"
                  f"{a['calmar']:6.2f}{a['trades']:6d}")
            if k == 1.5:
                b = bootstrap_dd(pd.Series(a["equity"], index=a["index"]).pct_change().fillna(0).to_numpy(), n=1200)
                print(f"        yearly " + " ".join(f"{y}:{v*100:+.0f}%" for y,v in a["yearly"].items())
                      + f"   bootstrap P(DD>20%) {b['p_dd_worse_than_20']*100:.0f}%")
