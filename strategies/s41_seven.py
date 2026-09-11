"""
S41 - Seven sleeves. The screen's own output, added back.

S40 put all 116 panel features through one identical book and kept only what
survived out of sample at low correlation to the incumbent. Two candidates came
back worth trading, and both read something no other sleeve reads:

  BTCDOM  BTC's share of dollar turnover across the perp complex,
          btc_quote_volume / (btc + 15 alts quote volume). Verified by
          reconstruction against the stored series (correlation 1.0000, max
          absolute difference 0.000000). Sign +1: when capital rotates INTO
          BTC and out of the alt complex, BTC leads. This is an attention and
          rotation signal - not price, not flow, not positioning, not vol.
          IS PF 1.51 / OOS PF 1.25, Sharpe 1.11, correlation 0.11.
  FUNDZ   fade the funding-rate z-score. Crowded longs pay to stay long.
          IS PF 1.21 / OOS PF 1.10, and correlation -0.03 - the only sleeve
          in the study that is NEGATIVELY correlated with the incumbent.

Multiple-testing discipline: 116 features x 2 signs were screened, 50 produced
enough trades to judge, 22 beat OOS PF 1.10 and 13 beat 1.30. In-sample rank
only ordered the queue; nothing was kept unless it also cleared out of sample
on a period the screen never saw.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s32_pair as s32
import strategies.s38_orth as s38
import strategies.s39_five as s39

FULL_START = s39.FULL_START
BV_START = s39.BV_START
EXTRA = {"BTCDOM": ("btc_dom_z", 1, 0.020), "FUNDZ": ("fund_z", -1, 0.018)}

def sleeves(k, s, e, use):
    out = s39.sleeves(k, s, e, tuple(u for u in use if u not in EXTRA))
    xf = s38.xpanel("12h"); xf = xf[xf.dt >= FULL_START].reset_index(drop=True)
    for tag in use:
        if tag not in EXTRA: continue
        col, sign, risk = EXTRA[tag]
        a = s38.book(xf, col, sign, thr=1.0, stp=3.0, rr=2.0)
        m = backtest(xf, a, "12h", start=s, end=e, risk=min(risk * k, 0.08),
                     max_lev=10.0, max_bars_h=7 * 24)
        out[tag] = s39.daily(m); out[f"_{tag}_n"] = m["trades"]
    return out

def weights(use, start):
    isl = s39.clip(sleeves(1, start, IS_END, use), start, IS_END)
    ic = [c for c in isl if not c.startswith("_")]
    inv = {c: 1.0 / max(isl[c].std(), 1e-9) for c in ic}
    t = sum(inv.values())
    return {c: inv[c] / t for c in ic}

def run(use, start, ks, tag, boot=True):
    W = weights(use, start)
    print(f"\n{tag}   weights " + " ".join(f"{c} {W[c]*100:.0f}%" for c in W))
    print(f"{'knob':>5} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}{'N':>6}"
          f" | {'IS':>7}{'OOS':>8} | {'medDD':>7}{'p05':>7}{'P>20%':>7}")
    for k in ks:
        r = {}
        for t2, s, e in (("IS", start, IS_END), ("OOS", IS_END, OOS_END), ("ALL", start, OOS_END)):
            r[t2] = s32.combine(s39.clip(sleeves(k, s, e, use), s, e), W)
        a = r["ALL"]
        line = (f"{k:>5} | {a['cagr']*100:7.1f}%{a['max_dd']*100:7.1f}%{a['pf']:6.2f}"
                f"{a['sharpe']:6.2f}{a['calmar']:6.2f}{a['trades']:6d} | "
                f"{r['IS']['cagr']*100:6.1f}%{r['OOS']['cagr']*100:7.1f}% | ")
        if boot:
            rr = pd.Series(a["equity"], index=a["index"]).pct_change().fillna(0).to_numpy()
            b = bootstrap_dd(rr, n=2000)
            line += f"{b['dd_median']*100:6.1f}%{b['dd_p05']*100:6.1f}%{b['p_dd_worse_than_20']*100:6.0f}%"
        print(line)
        print("        yearly " + " ".join(f"{y}:{v*100:+.0f}%" for y, v in a["yearly"].items()))

if __name__ == "__main__":
    full7 = ("FLOW", "POSN", "CONVEX", "CMPX", "ETHREL", "BTCDOM", "FUNDZ")
    s1 = s39.clip(sleeves(1, FULL_START, OOS_END, full7), FULL_START, OOS_END)
    cols = [c for c in s1 if not c.startswith("_")]
    print(f"FULL window {FULL_START} -> {OOS_END}  correlation:")
    print(pd.DataFrame({c: s1[c] for c in cols}).corr().round(3).to_string())
    run(full7, FULL_START, (2.0, 2.5, 3.0), "FULL 7-sleeve (no IVOL - BVOL starts 2023)")

    bv8 = ("FLOW", "POSN", "CONVEX", "IVOL", "CMPX", "ETHREL", "BTCDOM", "FUNDZ")
    s2 = s39.clip(sleeves(1, BV_START, OOS_END, bv8), BV_START, OOS_END)
    c2 = [c for c in s2 if not c.startswith("_")]
    print(f"\nBVOL window {BV_START} -> {OOS_END}  correlation:")
    print(pd.DataFrame({c: s2[c] for c in c2}).corr().round(3).to_string())
    run(bv8, BV_START, (2.5, 3.5, 4.5), "BVOL-window 8-sleeve")
