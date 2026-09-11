"""
S39 - Five sleeves: flow, positioning, convexity, implied vol, stablecoin basis.

The orthogonal-sleeve search (S38) turned up one strong new candidate and one
marginal one:

  CMPX   3-day momentum of log(BTCUSD_PERP / BTCUSDT_PERP). Both legs are
         BTC perpetuals, so BTC cancels and what is left is the market's
         implied USDT/USD rate - the stablecoin basis. It measures capital
         moving into and out of the crypto complex through the stablecoin
         door, which no price, flow or positioning series sees.
         IS 5.4% PF 1.20 -> OOS 20.0% PF 1.82 (out-of-sample stronger)
  ETHREL fade ETH's 3-day outperformance of BTC.
         IS 2.0% PF 1.08 -> OOS 10.9% PF 1.50

Both are available over the full 5.5-year window, unlike IVOL which starts
2023-06-20, so the portfolio is measured on both windows.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s32_pair as s32
import strategies.s36_ivmom as s36
import strategies.s38_orth as s38

FULL_START = "2021-03-01"
BV_START = "2023-06-21"

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def sleeves(k, s, e, use=("FLOW", "POSN", "CONVEX", "IVOL", "CMPX", "ETHREL")):
    out = {}
    base = s32.sleeves(k, s, e, with_convex=("CONVEX" in use))
    for c in ("FLOW", "POSN", "CONVEX"):
        if c in use and c in base:
            out[c] = base[c]; out[f"_{c}_n"] = base[f"_{c}_n"]
    if "IVOL" in use:
        f = s36.ivpanel("12h")
        a = s36.arrays(f, s36.signal(f, use_res=False), thr=0.7, atr_stop=3.0, rr=2.0)
        m = backtest(f, a, "12h", start=s, end=e, risk=min(0.020 * k, 0.08),
                     max_lev=10.0, max_bars_h=7 * 24)
        out["IVOL"] = daily(m); out["_IVOL_n"] = m["trades"]
    xf = s38.xpanel("12h")
    xf = xf[xf.dt >= FULL_START].reset_index(drop=True)
    for tag, col, sign, risk in (("CMPX", "f_cmpx", 1, 0.020), ("ETHREL", "f_ethrel", -1, 0.018)):
        if tag not in use: continue
        a = s38.book(xf, col, sign, thr=1.0, stp=3.0, rr=2.0)
        m = backtest(xf, a, "12h", start=s, end=e, risk=min(risk * k, 0.08),
                     max_lev=10.0, max_bars_h=7 * 24)
        out[tag] = daily(m); out[f"_{tag}_n"] = m["trades"]
    return out

def clip(sl, s, e):
    cols = [c for c in sl if not c.startswith("_")]
    idx = None
    for c in cols:
        i = sl[c].index
        i = i[(i >= pd.Timestamp(s, tz="UTC")) & (i < pd.Timestamp(e, tz="UTC"))]
        idx = i if idx is None else idx.union(i)
    out = {c: sl[c].reindex(idx).fillna(0.0) for c in cols}
    out.update({k2: v for k2, v in sl.items() if k2.startswith("_")})
    return out

def weights(use, start):
    isl = clip(sleeves(1, start, IS_END, use), start, IS_END)
    ic = [c for c in isl if not c.startswith("_")]
    inv = {c: 1.0 / max(isl[c].std(), 1e-9) for c in ic}
    t = sum(inv.values())
    return {c: inv[c] / t for c in ic}

def run(use, start, ks, tag, boot_at=None):
    W = weights(use, start)
    print(f"\n{tag}   weights " + " ".join(f"{c} {W[c]*100:.0f}%" for c in W))
    print(f"{'knob':>5} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}{'N':>6}"
          f" | {'IS CAGR':>8}{'DD':>7} | {'OOS CAGR':>9}{'DD':>7}")
    for k in ks:
        r = {}
        for lab, s, e in (("IS", start, IS_END), ("OOS", IS_END, OOS_END), ("ALL", start, OOS_END)):
            r[lab] = s32.combine(clip(sleeves(k, s, e, use), s, e), W)
        a = r["ALL"]
        line = (f"{k:>5} | {a['cagr']*100:7.1f}%{a['max_dd']*100:7.1f}%{a['pf']:6.2f}"
                f"{a['sharpe']:6.2f}{a['calmar']:6.2f}{a['trades']:6d} | "
                f"{r['IS']['cagr']*100:7.1f}%{r['IS']['max_dd']*100:6.1f}% | "
                f"{r['OOS']['cagr']*100:8.1f}%{r['OOS']['max_dd']*100:6.1f}%")
        if boot_at and abs(k - boot_at) < 1e-9:
            rr = pd.Series(a["equity"], index=a["index"]).pct_change().fillna(0).to_numpy()
            b = bootstrap_dd(rr, n=2000)
            line += f"  <- boot median DD {b['dd_median']*100:.1f}% P(DD>20%) {b['p_dd_worse_than_20']*100:.0f}%"
            print(line)
            print("        yearly " + " ".join(f"{y}:{v*100:+.0f}%" for y, v in a["yearly"].items()))
        else:
            print(line)

if __name__ == "__main__":
    full = ("FLOW", "POSN", "CONVEX", "CMPX", "ETHREL")
    s1 = clip(sleeves(1, FULL_START, OOS_END, full), FULL_START, OOS_END)
    cols = [c for c in s1 if not c.startswith("_")]
    print(f"full window {FULL_START} -> {OOS_END}  correlation:")
    print(pd.DataFrame({c: s1[c] for c in cols}).corr().round(3).to_string())

    run(("FLOW", "POSN", "CONVEX"), FULL_START, (1.5, 2.0), "FULL 3-sleeve baseline")
    run(("FLOW", "POSN", "CONVEX", "CMPX"), FULL_START, (1.5, 2.0, 2.5), "FULL +CMPX")
    run(full, FULL_START, (1.5, 2.0, 2.5, 3.0), "FULL +CMPX+ETHREL", boot_at=2.5)

    bv = ("FLOW", "POSN", "CONVEX", "IVOL", "CMPX", "ETHREL")
    s2 = clip(sleeves(1, BV_START, OOS_END, bv), BV_START, OOS_END)
    c2 = [c for c in s2 if not c.startswith("_")]
    print(f"\nBVOL window {BV_START} -> {OOS_END}  correlation:")
    print(pd.DataFrame({c: s2[c] for c in c2}).corr().round(3).to_string())
    run(bv, BV_START, (1.5, 2.0, 2.5, 3.0, 3.5), "BVOL-window 6-sleeve", boot_at=2.5)
