"""
S32 - Flow + Positioning pair   [BTCUSDT perp only]

The two best books in the study read different things. S31 reads AGGRESSIVE FLOW
(taker imbalance orthogonalised to recent returns, 12h bars). S7 reads
POSITIONING (how crowded retail and top-trader accounts are, 4h bars). They
share no input series, so the pair is a real test of whether diversification
still has anything to give once the market-neutral sleeve is gone.

Each book runs in its own sub-account and the pair is rebalanced monthly to
inverse-volatility weights fixed from in-sample data.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s07_smart as s07
import strategies.s31_ofi6 as s31
import strategies.s15_convex as s15

START = "2021-01-03"
_c = {}
def P(tf):
    if tf not in _c:
        fut, f = panel(tf)
        f = f[f.dt >= START].reset_index(drop=True)
        _c[tf] = f
    return _c[tf]

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def sleeves(k, s, e, with_convex=False):
    out = {}
    f12 = P("12h")
    a = s31.arrays(f12, s31.signal(f12), thr=1.0, atr_stop=3.0, rr=2.0)
    m = backtest(f12, a, "12h", start=s, end=e, risk=min(0.035*k, 0.14),
                 max_lev=10.0, max_bars_h=7*24)
    out["FLOW"] = daily(m); out["_FLOW_n"] = m["trades"]

    f4 = P("4h"); comp = s07.composite(f4)
    a = s07.arrays(f4, comp, thr=0.7, atr_stop=3.5, rr=2.5)
    m = backtest(f4, a, "4h", start=s, end=e, risk=min(0.025*k, 0.10),
                 max_lev=10.0, max_bars_h=10*24)
    out["POSN"] = daily(m); out["_POSN_n"] = m["trades"]

    if with_convex:
        a = s15.arrays(f4, comp=comp, trail_atr=3.0, stop_atr=2.5)
        m = backtest(f4, a, "4h", start=s, end=e, risk=min(0.015*k, 0.06),
                     max_lev=10.0, trail_after_r=1.0, pyramid=3, pyramid_step=1.0)
        out["CONVEX"] = daily(m); out["_CONVEX_n"] = m["trades"]
    return out

def combine(sl, w=None, eq0=10_000.0):
    cols = [c for c in sl if not c.startswith("_")]
    R = pd.DataFrame({c: sl[c] for c in cols}).fillna(0.0)
    w = w or {c: 1.0 for c in cols}
    wv = np.array([w[c] for c in cols], float); wv /= wv.sum()
    sli = eq0*wv; curve = []
    per = pd.Series(R.index).dt.tz_localize(None).dt.to_period("M").to_numpy(); prev = per[0]
    for i in range(len(R)):
        sli = sli*(1.0+R.iloc[i].to_numpy()); e = sli.sum()
        if e <= 0: curve.append(0.0); continue
        if per[i] != prev: sli = e*wv; prev = per[i]
        curve.append(e)
    e = np.array(curve); yrs = (R.index[-1]-R.index[0]).days/365.25
    peak = np.maximum.accumulate(e); dd = e/peak-1
    ret = pd.Series(e, index=R.index).pct_change().fillna(0)
    dp = pd.Series(e, index=R.index).diff().dropna()
    cagr = (e[-1]/eq0)**(1/yrs)-1 if e[-1] > 0 else -1.0
    ys={}; pv=eq0; es=pd.Series(e,index=R.index)
    for y,g in es.groupby(es.index.year): ys[int(y)]=float(g.iloc[-1]/pv-1); pv=g.iloc[-1]
    return dict(cagr=cagr, max_dd=float(dd.min()), trades=sum(sl[f"_{c}_n"] for c in cols),
                sharpe=float(ret.mean()/ret.std()*np.sqrt(365.25)) if ret.std()>0 else 0,
                calmar=float(cagr/abs(dd.min())) if dd.min()<0 else np.inf,
                pf=float(dp[dp>0].sum()/-dp[dp<0].sum()) if (dp<0).any() else np.inf,
                equity=e, index=R.index, yearly=ys)

if __name__ == "__main__":
    s1 = sleeves(1, START, IS_END, with_convex=True)
    cols = [c for c in s1 if not c.startswith("_")]
    print("in-sample daily-return correlation:")
    print(pd.DataFrame({c: s1[c] for c in cols}).corr().round(3).to_string())
    for wc in (False, True):
        s1b = sleeves(1, START, IS_END, with_convex=wc)
        cc = [c for c in s1b if not c.startswith("_")]
        inv = {c: 1.0/max(s1b[c].std(), 1e-9) for c in cc}
        tot = sum(inv.values()); rp = {c: inv[c]/tot for c in cc}
        print(f"\n--- sleeves: {', '.join(cc)}   weights " +
              " ".join(f"{c} {rp[c]*100:.0f}%" for c in cc))
        print(f"{'knob':>5} | {'IS CAGR':>9}{'DD':>8} | {'OOS CAGR':>9}{'DD':>8} | "
              f"{'ALL CAGR':>9}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}{'N':>6}")
        for k in (1, 1.5, 2, 3):
            r = {lab: combine(sleeves(k, s, e, with_convex=wc), rp)
                 for lab, s, e in (("IS", START, IS_END), ("OOS", IS_END, OOS_END),
                                   ("ALL", START, OOS_END))}
            a = r["ALL"]
            print(f"{k:>5} | {r['IS']['cagr']*100:8.1f}%{r['IS']['max_dd']*100:7.1f}% | "
                  f"{r['OOS']['cagr']*100:8.1f}%{r['OOS']['max_dd']*100:7.1f}% | "
                  f"{a['cagr']*100:8.1f}%{a['max_dd']*100:7.1f}%{a['pf']:6.2f}{a['sharpe']:6.2f}"
                  f"{a['calmar']:6.2f}{a['trades']:6d}")
            if k in (2, 3):
                b = bootstrap_dd(pd.Series(a["equity"], index=a["index"]).pct_change().fillna(0).to_numpy(), n=1200)
                print(f"        yearly " + " ".join(f"{y}:{v*100:+.0f}%" for y,v in a["yearly"].items())
                      + f"   bootstrap P(DD>20%) {b['p_dd_worse_than_20']*100:.0f}%")
