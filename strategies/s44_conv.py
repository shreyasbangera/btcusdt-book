"""
S44 - Conviction sizing across the whole book.

The ceiling is s / sqrt(rho-bar). rho-bar will not move. s can: the engine was
throwing away information it already had. Every sleeve emits a z-score and then
collapsed it to +/-1 at the entry, so a 3-sigma signal and a 1.01-sigma signal
were the same bet. Letting |z| scale the risk budget - capped, so one signal
cannot take the account - raised out-of-sample Sharpe on all four books tested
and overall Sharpe on three:

    IVOL   1.41 -> 1.61   (OOS 1.07 -> 1.33)
    CMPX   0.99 -> 1.27   (OOS 1.64 -> 1.75)
    FLOW   1.22 -> 1.26   (OOS 1.35 -> 1.41)
    BTCDOM 1.11 -> 1.13   (OOS 0.72 -> 0.82)

The instructive contrast is that conviction FILTERING fails where conviction
SIZING works. Trading only |z| > 1.5x threshold cuts Sharpe roughly in half on
every book. So the extremes do not carry the edge - the edge is monotone in |z|,
and the ordering is the information. That is what a real IC looks like, and it
is a stronger check on the signals than any single backtest.

One cap for every sleeve (2x), no per-book tuning, so this is a rule rather
than a fit.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs
import strategies.s32_pair as s32
import strategies.s36_ivmom as s36
import strategies.s38_orth as s38
import strategies.s39_five as s39
import strategies.s07_smart as s07
import strategies.s15_convex as s15
import strategies.s31_ofi6 as s31

FULL_START = "2021-03-01"; BV_START = "2023-06-21"
CAP = 2.0

def conv(s, thr):
    """+/-1 scaled by |z|/thr, capped. Zero inside the threshold band."""
    e = np.where(s > thr, 1.0, np.where(s < -thr, -1.0, 0.0))
    w = np.clip(np.abs(s) / thr, 1.0, CAP)
    return np.nan_to_num(e * w)

_P = {}
def P(tf):
    if tf not in _P:
        _, f = panel(tf)
        _P[tf] = f[f.dt >= FULL_START].reset_index(drop=True)
    return _P[tf]

def sleeves(k, s, e, use, cap=0.30, conviction=True, dom_hold=7):
    out = {}
    mk = conv if conviction else (lambda z, t: np.where(z > t, 1.0, np.where(z < -t, -1.0, 0.0)))
    def add(tag, f, sig, thr, tf, risk, hold_d=7, stp=3.0, rr=2.0):
        a = f.atr14.to_numpy(float)
        arr = dict(entry=mk(sig, thr), stop=stp * a, tp=stp * rr * a, exit=np.zeros(len(f)))
        m = backtest(f, arr, tf, start=s, end=e, risk=min(risk * k, cap),
                     max_lev=10.0, max_bars_h=hold_d * 24)
        out[tag] = s39.daily(m); out[f"_{tag}_n"] = m["trades"]

    if "FLOW" in use:
        f = P("12h"); add("FLOW", f, zs(f.ofi6_res.to_numpy(float), 480), 1.0, "12h", 0.035)
    if "POSN" in use:
        f = P("4h"); add("POSN", f, s07.composite(f), 0.7, "4h", 0.025, stp=3.5, rr=2.5, hold_d=10)
    if "CONVEX" in use:
        f = P("4h"); c15 = s15.arrays(f, comp=s07.composite(f), trail_atr=3.0, stop_atr=2.5)
        m = backtest(f, c15, "4h", start=s, end=e, risk=min(0.015 * k, cap),
                     max_lev=10.0, trail_after_r=1.0, pyramid=3, pyramid_step=1.0)
        out["CONVEX"] = s39.daily(m); out["_CONVEX_n"] = m["trades"]
    if "IVOL" in use:
        f = s36.ivpanel("12h"); add("IVOL", f, s36.signal(f, use_res=False), 0.7, "12h", 0.020)
    xf = s38.xpanel("12h"); xf = xf[xf.dt >= FULL_START].reset_index(drop=True)
    spec = {"CMPX": ("f_cmpx", 1, 0.020, 7), "ETHREL": ("f_ethrel", -1, 0.018, 7),
            "BTCDOM": ("btc_dom_z", 1, 0.020, dom_hold), "FUNDZ": ("fund_z", -1, 0.018, 7)}
    for tag in use:
        if tag not in spec: continue
        col, sign, risk, hold = spec[tag]
        add(tag, xf, sign * xf[col].to_numpy(float), 1.0, "12h", risk, hold_d=hold)
    return out

def weights(use, start, **kw):
    isl = s39.clip(sleeves(1, start, IS_END, use, **kw), start, IS_END)
    ic = [c for c in isl if not c.startswith("_")]
    inv = {c: 1.0 / max(isl[c].std(), 1e-9) for c in ic}
    t = sum(inv.values()); return {c: inv[c] / t for c in ic}

def run(use, start, ks, tag, **kw):
    W = weights(use, start, **kw)
    print(f"\n{tag}   weights " + " ".join(f"{c} {W[c]*100:.0f}%" for c in W))
    print(f"{'knob':>5} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}{'N':>6}"
          f" | {'IS':>7}{'OOS':>8} | {'medDD':>7}{'P>20%':>7}")
    for k in ks:
        r = {}
        for t2, s, e in (("IS", start, IS_END), ("OOS", IS_END, OOS_END), ("ALL", start, OOS_END)):
            r[t2] = s32.combine(s39.clip(sleeves(k, s, e, use, **kw), s, e), W)
        a = r["ALL"]
        rr = pd.Series(a["equity"], index=a["index"]).pct_change().fillna(0).to_numpy()
        b = bootstrap_dd(rr, n=2000)
        print(f"{k:>5} | {a['cagr']*100:7.1f}%{a['max_dd']*100:7.1f}%{a['pf']:6.2f}{a['sharpe']:6.2f}"
              f"{a['calmar']:6.2f}{a['trades']:6d} | {r['IS']['cagr']*100:6.1f}%"
              f"{r['OOS']['cagr']*100:7.1f}% | {b['dd_median']*100:6.1f}%"
              f"{b['p_dd_worse_than_20']*100:6.0f}%")
        print("        yearly " + " ".join(f"{y}:{v*100:+.0f}%" for y, v in a["yearly"].items()))

if __name__ == "__main__":
    bv8 = ("FLOW", "POSN", "CONVEX", "IVOL", "CMPX", "ETHREL", "BTCDOM", "FUNDZ")
    full7 = ("FLOW", "POSN", "CONVEX", "CMPX", "ETHREL", "BTCDOM", "FUNDZ")
    run(bv8, BV_START, (2.5, 3.5, 4.5), "BVOL 8-sleeve, flat sizing (control)", conviction=False)
    run(bv8, BV_START, (2.5, 3.5, 4.5), "BVOL 8-sleeve, CONVICTION sizing")
    run(bv8, BV_START, (3.5,), "BVOL 8-sleeve, conviction + 14d dominance hold", dom_hold=14)
    run(full7, FULL_START, (2.0, 3.0), "FULL 7-sleeve, flat sizing (control)", conviction=False)
    run(full7, FULL_START, (2.0, 3.0), "FULL 7-sleeve, CONVICTION sizing")
