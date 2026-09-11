"""
S26 - Adaptive Sleeve Allocation (ASA)   [BTCUSDT perp only]

Fixed risk-parity weights assume every book's edge is stationary. It is not:
the trend books earn in directional regimes and give it back in chop, while the
positioning book is closer to regime-neutral. This allocates each month in
proportion to each sleeve's TRAILING risk-adjusted performance, so capital
migrates toward whatever is currently working.

Weights are formed from a lookback window ending at the previous month, so the
allocation for month M uses only data available before M starts.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import IS_START, IS_END, OOS_END
from research.robust import bootstrap_dd
from strategies.s19_futonly import sleeves

START = "2021-01-03"

def adaptive(sl, lookback_m=6, mode="sharpe", floor=0.05, eq0=10_000.0):
    cols = [c for c in sl if not c.startswith("_")]
    R = pd.DataFrame({c: sl[c] for c in cols}).fillna(0.0)
    idx = R.index
    month = pd.Series(idx).dt.tz_localize(None).dt.to_period("M").to_numpy()
    eq = eq0
    slices = np.full(len(cols), eq0/len(cols))
    curve = []
    prev = month[0]
    w = np.full(len(cols), 1.0/len(cols))
    for i in range(len(R)):
        slices = slices*(1.0+R.iloc[i].to_numpy())
        eq = slices.sum()
        if eq <= 0:
            curve.append(0.0); continue
        if month[i] != prev:
            # re-weight using only data strictly before this month
            hist = R.iloc[:i]
            cut = hist.index[-1] - pd.Timedelta(days=30*lookback_m)
            hh = hist[hist.index >= cut]
            if len(hh) > 40:
                if mode == "sharpe":
                    sc = hh.mean()/hh.std().replace(0, np.nan)
                else:
                    sc = hh.mean()
                sc = sc.fillna(0.0).clip(lower=0.0).to_numpy()
                if sc.sum() > 0:
                    w = sc/sc.sum()
                    w = np.maximum(w, floor); w = w/w.sum()
                else:
                    w = np.full(len(cols), 1.0/len(cols))
            slices = eq*w
            prev = month[i]
        curve.append(eq)
    e = np.array(curve); yrs = (idx[-1]-idx[0]).days/365.25
    peak = np.maximum.accumulate(e); dd = e/peak-1
    ret = pd.Series(e, index=idx).pct_change().fillna(0)
    dp = pd.Series(e, index=idx).diff().dropna()
    cagr = (e[-1]/eq0)**(1/yrs)-1 if e[-1] > 0 else -1.0
    return dict(cagr=cagr, max_dd=float(dd.min()),
                sharpe=float(ret.mean()/ret.std()*np.sqrt(365.25)) if ret.std() > 0 else 0,
                calmar=float(cagr/abs(dd.min())) if dd.min() < 0 else np.inf,
                pf=float(dp[dp > 0].sum()/-dp[dp < 0].sum()) if (dp < 0).any() else np.inf,
                trades=sum(sl[f"_{c}_n"] for c in cols), equity=e, index=idx)

if __name__ == "__main__":
    from strategies.s19_futonly import combine
    print("S26 Adaptive Sleeve Allocation vs fixed weights")
    print(f"{'scheme':<28}{'knob':>5} | {'IS CAGR':>9}{'DD':>8} | {'OOS CAGR':>9}{'DD':>8} | "
          f"{'ALL CAGR':>9}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}")
    for knob in (2, 3):
        cache = {lab: sleeves(knob, s, e)
                 for lab, s, e in (("IS", START, IS_END), ("OOS", IS_END, OOS_END), ("ALL", START, OOS_END))}
        rows = [("fixed equal weight", lambda sl: combine(sl))]
        for lb in (3, 6, 12):
            for mode in ("sharpe", "mean"):
                rows.append((f"adaptive {mode} {lb}m",
                             lambda sl, lb=lb, mode=mode: adaptive(sl, lookback_m=lb, mode=mode)))
        for name, fn in rows:
            r = {lab: fn(cache[lab]) for lab in ("IS", "OOS", "ALL")}
            a = r["ALL"]
            pf = a.get("pf", a.get("profit_factor", float("nan")))
            print(f"{name:<28}{knob:>5} | {r['IS']['cagr']*100:8.1f}%{r['IS']['max_dd']*100:7.1f}% | "
                  f"{r['OOS']['cagr']*100:8.1f}%{r['OOS']['max_dd']*100:7.1f}% | "
                  f"{a['cagr']*100:8.1f}%{a['max_dd']*100:7.1f}%{pf:6.2f}{a['sharpe']:6.2f}{a['calmar']:6.2f}")
