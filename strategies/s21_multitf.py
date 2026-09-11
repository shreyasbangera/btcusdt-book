"""
S21 - Multi-timeframe ensemble of the positioning book  [BTCUSDT perp only]

The engine holds one position at a time, so a single book's Sharpe is limited by
how often it is in the market. Running the SAME signal on several decision
timeframes as separate sub-accounts is genuine time-diversification: each sleeve
enters on its own clock, so their entry timing decorrelates even though the
underlying edge is identical.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s07_smart as s07

TFS = ["2h", "4h", "8h", "12h", "1D"]
START = "2021-01-03"
_P = {}
def get(tf):
    if tf not in _P:
        fut, f = panel(tf)
        f = f[f.dt >= START].reset_index(drop=True)
        _P[tf] = (f, s07.composite(f))
    return _P[tf]

def daily(eq, dt):
    return pd.Series(eq, index=pd.to_datetime(dt)).resample("1D").last().dropna().pct_change().fillna(0.0)

def sleeves(risk, start, end):
    out = {}
    for tf in TFS:
        f, comp = get(tf)
        a = s07.arrays(f, comp, thr=0.7, atr_stop=3.5, rr=2.5)
        m = backtest(f, a, tf, start=start, end=end, risk=risk, max_lev=10.0, max_bars_h=10*24)
        out[tf] = daily(m["equity"], m["dt"]); out["_" + tf + "_n"] = m["trades"]
    return out

def combine(sl, eq0=10_000.0):
    cols = [c for c in sl if not c.startswith("_")]
    R = pd.DataFrame({c: sl[c] for c in cols}).fillna(0.0)
    wv = np.full(len(cols), 1.0/len(cols))
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
    return dict(cagr=cagr, max_dd=float(dd.min()),
                trades=sum(sl[f"_{c}_n"] for c in cols),
                sharpe=float(ret.mean()/ret.std()*np.sqrt(365.25)) if ret.std() > 0 else 0,
                calmar=float(cagr/abs(dd.min())) if dd.min() < 0 else np.inf,
                pf=float(dp[dp > 0].sum()/-dp[dp < 0].sum()) if (dp < 0).any() else np.inf,
                equity=e, index=R.index, R=R)

if __name__ == "__main__":
    s1 = sleeves(0.01, START, IS_END)
    print("timeframe-sleeve correlation (IS daily returns):")
    print(pd.DataFrame({c: s1[c] for c in TFS}).corr().round(3).to_string())
    print("\nper-sleeve IS Sharpe: " + "  ".join(
        f"{tf}:{s1[tf].mean()/s1[tf].std()*np.sqrt(365.25):.2f}" for tf in TFS))
    print(f"\n{'risk':>6} | {'IS CAGR':>9}{'DD':>8} | {'OOS CAGR':>9}{'DD':>8} | "
          f"{'ALL CAGR':>9}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}{'N':>6}")
    for risk in (0.01, 0.02, 0.035, 0.05, 0.08):
        r = {lab: combine(sleeves(risk, s, e))
             for lab, s, e in (("IS", START, IS_END), ("OOS", IS_END, OOS_END), ("ALL", START, OOS_END))}
        a = r["ALL"]
        print(f"{risk*100:5.1f}% | {r['IS']['cagr']*100:8.1f}%{r['IS']['max_dd']*100:7.1f}% | "
              f"{r['OOS']['cagr']*100:8.1f}%{r['OOS']['max_dd']*100:7.1f}% | "
              f"{a['cagr']*100:8.1f}%{a['max_dd']*100:7.1f}%{a['pf']:6.2f}{a['sharpe']:6.2f}"
              f"{a['calmar']:6.2f}{a['trades']:6d}")
