"""
S19 - Futures-only portfolio (no spot leg anywhere).

The earlier portfolio leaned 47.8% on a long-spot / short-perp carry sleeve.
This study is futures-only, so that sleeve is removed and nothing replaces it -
the futures-native substitute (quarterly-vs-perp calendar spread) was measured at
-1.3% annualised with a 49% hit rate, i.e. no edge, because once both legs are
futures the funding sits on both sides.

What remains is four directional books on the BTCUSDT perpetual:
  SMRD   smart-money vs retail positioning, fixed 2.5R target
  CONVEX same entry, no target, ATR trail, pyramided  (S15)
  OFS    order flow orthogonalised to past returns
  AVT    Donchian breakout gated by ADX + efficiency ratio
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_START, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s07_smart as s07
import strategies.s03_ofi_swing as s03
import strategies.s04_advol as s04
import strategies.s15_convex as s15

_c = {}
def panels():
    if not _c:
        fut, f4 = panel("4h")
        fm = f4[f4.dt >= "2021-01-03"].reset_index(drop=True)
        _c.update(f4=f4, fm=fm, comp=s07.composite(fm))
    return _c

def daily(eq, dt):
    return pd.Series(eq, index=pd.to_datetime(dt)).resample("1D").last().dropna().pct_change().fillna(0.0)

def sleeves(k, start, end):
    P = panels(); f4, fm, comp = P["f4"], P["fm"], P["comp"]
    out = {}
    a = s07.arrays(fm, comp, thr=0.7, atr_stop=3.5, rr=2.5)
    m = backtest(fm, a, "4h", start=start, end=end, risk=min(0.012*k, 0.10),
                 max_lev=10.0, max_bars_h=10*24)
    out["SMRD"] = daily(m["equity"], m["dt"]); out["_SMRD_n"] = m["trades"]

    a = s15.arrays(fm, comp=comp, trail_atr=3.0, stop_atr=2.5)
    m = backtest(fm, a, "4h", start=start, end=end, risk=min(0.010*k, 0.05),
                 max_lev=10.0, trail_after_r=1.0, pyramid=3, pyramid_step=1.0)
    out["CONVEX"] = daily(m["equity"], m["dt"]); out["_CONVEX_n"] = m["trades"]

    a = s03.arrays(f4, thr=0.75, atr_stop=3.5, rr=2.5, trend_filter=True, flow="ofi24_resz")
    m = backtest(f4, a, "4h", start=start, end=end, risk=min(0.015*k, 0.12),
                 max_lev=10.0, max_bars_h=10*24)
    out["OFS"] = daily(m["equity"], m["dt"]); out["_OFS_n"] = m["trades"]

    a = s04.arrays(f4, dc_n=40, adx_min=20, er_min=0.30, vol_adapt=False)
    m = backtest(f4, a, "4h", start=start, end=end, risk=min(0.009*k, 0.09),
                 max_lev=10.0, trail_after_r=1.0)
    out["AVT"] = daily(m["equity"], m["dt"]); out["_AVT_n"] = m["trades"]
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
    ntr = sum(sl[f"_{c}_n"] for c in cols)
    ys = {}; pv = eq0; es = pd.Series(e, index=R.index)
    for y, g in es.groupby(es.index.year): ys[int(y)] = float(g.iloc[-1]/pv-1); pv = g.iloc[-1]
    return dict(cagr=cagr, max_dd=float(dd.min()), trades=int(ntr),
                sharpe=float(ret.mean()/ret.std()*np.sqrt(365.25)) if ret.std() > 0 else 0,
                calmar=float(cagr/abs(dd.min())) if dd.min() < 0 else np.inf,
                pf=float(dp[dp > 0].sum()/-dp[dp < 0].sum()) if (dp < 0).any() else np.inf,
                equity=e, index=R.index, yearly=ys, R=R)

if __name__ == "__main__":
    sl1 = sleeves(1, "2021-01-03", IS_END)
    cols = [c for c in sl1 if not c.startswith("_")]
    print("sleeve correlation (in-sample daily returns):")
    print(pd.DataFrame({c: sl1[c] for c in cols}).corr().round(3).to_string())
    inv = {c: 1.0/max(sl1[c].std(), 1e-9) for c in cols}
    tot = sum(inv.values()); rp = {c: inv[c]/tot for c in cols}
    print("\nrisk-parity weights (IS):", {c: f"{rp[c]*100:.1f}%" for c in cols})
    print(f"\n{'knob':>5} | {'IS CAGR':>9}{'DD':>8} | {'OOS CAGR':>9}{'DD':>8} | "
          f"{'ALL CAGR':>9}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}{'N':>6}")
    for k in (1, 2, 3, 4, 6, 8, 11):
        r = {lab: combine(sleeves(k, s, e), rp)
             for lab, s, e in (("IS", "2021-01-03", IS_END), ("OOS", IS_END, OOS_END),
                               ("ALL", "2021-01-03", OOS_END))}
        a = r["ALL"]
        print(f"{k:>5} | {r['IS']['cagr']*100:8.1f}%{r['IS']['max_dd']*100:7.1f}% | "
              f"{r['OOS']['cagr']*100:8.1f}%{r['OOS']['max_dd']*100:7.1f}% | "
              f"{a['cagr']*100:8.1f}%{a['max_dd']*100:7.1f}%{a['pf']:6.2f}{a['sharpe']:6.2f}"
              f"{a['calmar']:6.2f}{a['trades']:6d}")
        if k in (4, 6, 8):
            b = bootstrap_dd(pd.Series(a["equity"], index=a["index"]).pct_change().fillna(0).to_numpy(), n=1200)
            print(f"        yearly " + " ".join(f"{y}:{v*100:+.0f}%" for y, v in a["yearly"].items()))
            print(f"        bootstrap DD median {b['dd_median']*100:.1f}%  P(DD>20%) {b['p_dd_worse_than_20']*100:.0f}%")
