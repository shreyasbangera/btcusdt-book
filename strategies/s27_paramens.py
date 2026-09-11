"""
S27 - Parameter Ensemble (PE)   [BTCUSDT perp only]

Every result so far picked ONE parameter set per book. S16 showed what that
costs: grid-searching 480 configurations produced an in-sample CAGR of 73.3%
that delivered 20.2% out of sample. The standard defence is not a better search
but to stop searching - run the whole neighbourhood simultaneously in equal
size and take the average.

That trades peak in-sample performance for stability: the ensemble can never be
the best single configuration in hindsight, but it also cannot be the one that
happened to fit the sample.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd, itertools
from research.harness import panel, backtest, IS_START, IS_END, OOS_END
import strategies.s07_smart as s07

START = "2021-01-03"
fut, f4 = panel("4h")
fm = f4[f4.dt >= START].reset_index(drop=True)
comp = s07.composite(fm)

GRID = list(itertools.product((0.5, 0.7, 0.9, 1.1),      # signal threshold
                              (2.5, 3.5, 4.5),            # ATR stop
                              (2.0, 2.5, 3.0),            # reward:risk
                              (5, 10)))                   # holding-period cap, days

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def metrics(R, eq0=10_000.0):
    e = eq0*(1+R).cumprod()
    yrs = (R.index[-1]-R.index[0]).days/365.25
    peak = np.maximum.accumulate(e.to_numpy()); dd = e.to_numpy()/peak - 1
    dp = e.diff().dropna()
    cagr = (e.iloc[-1]/eq0)**(1/yrs)-1 if e.iloc[-1] > 0 else -1.0
    return dict(cagr=cagr, max_dd=float(dd.min()),
                sharpe=float(R.mean()/R.std()*np.sqrt(365.25)) if R.std() > 0 else 0,
                calmar=float(cagr/abs(dd.min())) if dd.min() < 0 else np.inf,
                pf=float(dp[dp > 0].sum()/-dp[dp < 0].sum()) if (dp < 0).any() else np.inf)

if __name__ == "__main__":
    print(f"running {len(GRID)} configurations as an equal-weight ensemble (risk 2.5% each,")
    print("scaled by 1/N so total risk matches a single book)\n")
    for lab, s, e in (("IS ", START, IS_END), ("OOS", IS_END, OOS_END), ("ALL", START, OOS_END)):
        rets, singles, ntr = [], [], 0
        for thr, st, rr, hold in GRID:
            a = s07.arrays(fm, comp, thr=thr, atr_stop=st, rr=rr)
            m = backtest(fm, a, "4h", start=s, end=e, risk=0.025, max_lev=10.0,
                         max_bars_h=hold*24)
            if m["trades"] < 20: continue
            rets.append(daily(m)); singles.append(m); ntr += m["trades"]
        R = pd.concat(rets, axis=1).fillna(0.0)
        ens = R.mean(axis=1)
        em = metrics(ens)
        sc = np.array([x["cagr"] for x in singles])
        sd = np.array([x["max_dd"] for x in singles])
        ss = np.array([x["sharpe"] for x in singles])
        print(f"{lab} ensemble  CAGR {em['cagr']*100:7.1f}%  DD {em['max_dd']*100:6.1f}%  "
              f"PF {em['pf']:5.2f}  Sharpe {em['sharpe']:5.2f}  Calmar {em['calmar']:5.2f}  "
              f"N(all cfg) {ntr}")
        print(f"    single configs: CAGR median {np.median(sc)*100:6.1f}% "
              f"[{sc.min()*100:.1f} … {sc.max()*100:.1f}]   "
              f"DD median {np.median(sd)*100:6.1f}%   Sharpe median {np.median(ss):.2f}")
        print(f"    ensemble Sharpe vs median single: {em['sharpe']-np.median(ss):+.2f}\n")
