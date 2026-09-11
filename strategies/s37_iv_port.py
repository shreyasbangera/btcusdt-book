"""
S37 - Adding the implied-volatility sleeve to the portfolio.

S36 reads the options market; S32's three sleeves read aggressive flow (S31),
positioning (S7) and trend convexity (S15). If IV momentum is genuinely a new
input class rather than a repackaging of price, its daily returns should be
close to uncorrelated with all three - which is worth more to a portfolio than
any amount of standalone strength.

The window is the binding constraint: BVOL starts 2023-06-20, so the whole
portfolio has to be re-measured on 2023-06-21 -> 2026-08-31 (3.2y) rather than
the 5.7y the other books use. In-sample ends at the study's usual 2024-07-01,
leaving 2.17y out-of-sample - most of this book's life is OOS.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s32_pair as s32
import strategies.s36_ivmom as s36

START = "2023-06-21"

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def sleeves(k, s, e):
    out = s32.sleeves(k, s, e, with_convex=True)
    f = s36.ivpanel("12h")
    a = s36.arrays(f, s36.signal(f, use_res=False), thr=0.7, atr_stop=3.0, rr=2.0)
    m = backtest(f, a, "12h", start=s, end=e, risk=min(0.020 * k, 0.08),
                 max_lev=10.0, max_bars_h=7 * 24)
    out["IVOL"] = daily(m); out["_IVOL_n"] = m["trades"]
    return out

def clip(sl, s, e):
    """Trim every sleeve to the common window and re-index on a shared calendar."""
    cols = [c for c in sl if not c.startswith("_")]
    idx = None
    for c in cols:
        i = sl[c].index
        i = i[(i >= pd.Timestamp(s, tz="UTC")) & (i < pd.Timestamp(e, tz="UTC"))]
        idx = i if idx is None else idx.union(i)
    out = {c: sl[c].reindex(idx).fillna(0.0) for c in cols}
    out.update({k2: v for k2, v in sl.items() if k2.startswith("_")})
    return out

if __name__ == "__main__":
    s1 = clip(sleeves(1, START, OOS_END), START, OOS_END)
    cols = [c for c in s1 if not c.startswith("_")]
    print(f"window {START} -> {OOS_END}   daily-return correlation:")
    print(pd.DataFrame({c: s1[c] for c in cols}).corr().round(3).to_string())
    print("\nstandalone, risk knob 1, over the same window:")
    for c in cols:
        r = s1[c]; e = 10_000 * (1 + r).cumprod()
        yrs = (r.index[-1] - r.index[0]).days / 365.25
        dd = (e / np.maximum.accumulate(e) - 1).min()
        print(f"  {c:>7} CAGR {((e.iloc[-1]/1e4)**(1/yrs)-1)*100:6.1f}%  DD {dd*100:6.1f}%"
              f"  Shp {r.mean()/r.std()*np.sqrt(365.25):5.2f}  N {s1['_'+c+'_n']:4d}")

    isl = clip(sleeves(1, START, IS_END), START, IS_END)
    ic = [c for c in isl if not c.startswith("_")]
    inv = {c: 1.0 / max(isl[c].std(), 1e-9) for c in ic}
    tot = sum(inv.values()); W = {c: inv[c] / tot for c in ic}
    print("\nweights fixed in-sample:", {c: round(v, 3) for c, v in W.items()})

    print(f"\n{'sleeves':>26}{'knob':>6} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}{'N':>6}"
          f" | {'IS CAGR':>8}{'DD':>7} | {'OOS CAGR':>9}{'DD':>7}")
    for use_iv in (False, True):
        for k in (1.0, 1.5, 2.0, 2.5, 3.0):
            def cut(sl):
                if use_iv: return sl
                return {c: v for c, v in sl.items() if not c.startswith("IVOL") and c != "_IVOL_n"}
            w = {c: v for c, v in W.items() if use_iv or c != "IVOL"}
            r = {}
            for lab, s, e in (("IS", START, IS_END), ("OOS", IS_END, OOS_END), ("ALL", START, OOS_END)):
                r[lab] = s32.combine(cut(clip(sleeves(k, s, e), s, e)), w)
            a = r["ALL"]
            lab = "FLOW+POSN+CONVEX" + ("+IVOL" if use_iv else "")
            print(f"{lab:>26}{k:>6} | {a['cagr']*100:7.1f}%{a['max_dd']*100:7.1f}%{a['pf']:6.2f}"
                  f"{a['sharpe']:6.2f}{a['calmar']:6.2f}{a['trades']:6d} | "
                  f"{r['IS']['cagr']*100:7.1f}%{r['IS']['max_dd']*100:6.1f}% | "
                  f"{r['OOS']['cagr']*100:8.1f}%{r['OOS']['max_dd']*100:6.1f}%")

def detail(k=2.7):
    """Finer look at the operating point, with a stationary-block bootstrap."""
    isl = clip(sleeves(1, START, IS_END), START, IS_END)
    ic = [c for c in isl if not c.startswith("_")]
    inv = {c: 1.0 / max(isl[c].std(), 1e-9) for c in ic}
    tot = sum(inv.values()); W = {c: inv[c] / tot for c in ic}
    a = s32.combine(clip(sleeves(k, START, OOS_END), START, OOS_END), W)
    r = pd.Series(a["equity"], index=a["index"]).pct_change().fillna(0).to_numpy()
    b = bootstrap_dd(r, n=2000)
    print(f"knob {k}: CAGR {a['cagr']*100:.1f}%  DD {a['max_dd']*100:.1f}%  PF {a['pf']:.2f} "
          f"Shp {a['sharpe']:.2f}  Clm {a['calmar']:.2f}  N {a['trades']}")
    print("  yearly " + " ".join(f"{y}:{v*100:+.0f}%" for y, v in a["yearly"].items()))
    print(f"  bootstrap P(DD worse than 20%) = {b['p_dd_worse_than_20']*100:.0f}%"
          f"   median DD {b['dd_median']*100:.1f}%  5th pct {b['dd_p05']*100:.1f}%")
    return a
