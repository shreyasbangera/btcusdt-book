"""
Full validation of the stability-screened flow book: IC of the exact traded
signal in each window, cost stress, block bootstrap, 1-minute execution, and
risk calibrated to the 20% drawdown limit.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from scipy import stats
import research.harness as H
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs
import strategies.s31_ofi6 as s31

START = "2021-01-03"
CFGS = [("12h", 1.0, 3.0, 2.0, 7), ("12h", 1.0, 3.0, 2.0, 12), ("6h", 1.3, 3.5, 2.5, 7)]

for tf, thr, stp, rr, hold in CFGS:
    fut, f = panel(tf); f = f[f.dt >= START].reset_index(drop=True)
    s = s31.signal(f)
    c = f.close.to_numpy(); ism = (f.dt < IS_END).to_numpy()
    hb = int(tf[:-1])
    print(f"\n{'='*74}\n{tf} thr{thr} stop{stp} rr{rr} hold{hold}d")
    # IC of the EXACT traded signal
    row = "  IC of traded signal   "
    for hh in (24//hb, 96//hb):
        y = (np.log(pd.Series(c).shift(-hh)) - np.log(pd.Series(c))).to_numpy()
        mi = np.isfinite(s)&np.isfinite(y)&ism; mo = np.isfinite(s)&np.isfinite(y)&~ism
        ri,_ = stats.spearmanr(s[mi], y[mi]); ro,_ = stats.spearmanr(s[mo], y[mo])
        row += f"h={hh*hb}h IS {ri:+.4f} OOS {ro:+.4f}   "
    print(row)
    a = s31.arrays(f, s, thr=thr, atr_stop=stp, rr=rr)
    # risk calibrated so the full-period drawdown sits just inside 20%
    for risk in (0.025, 0.035, 0.045):
        o = {lab: backtest(f, a, tf, start=ss, end=ee, risk=risk, max_lev=10.0,
                           max_bars_h=hold*24)
             for lab, ss, ee in (("IS",START,IS_END),("OOS",IS_END,OOS_END),("ALL",START,OOS_END))}
        m = o["ALL"]
        print(f"  risk {risk*100:.1f}%  ALL CAGR {m['cagr']*100:6.1f}%  DD {m['max_dd']*100:6.1f}%  "
              f"PF {m['profit_factor']:.2f}  N {m['trades']:4d}  WR {m['win_rate']*100:.1f}%  "
              f"Shp {m['sharpe']:.2f}  Clm {m['calmar']:.2f}  | IS {o['IS']['cagr']*100:5.1f}% "
              f"OOS {o['OOS']['cagr']*100:5.1f}% (PF {o['OOS']['profit_factor']:.2f}, N {o['OOS']['trades']})")
    # cost stress + bootstrap at 2.5%
    print("  cost stress (CAGR / PF / DD): ", end="")
    for mult in (1.0, 1.5, 2.0):
        m = backtest(f, a, tf, start=START, end=OOS_END, risk=0.025, max_lev=10.0,
                     max_bars_h=hold*24, fee=5.0*mult, slip=3.0*mult)
        print(f"{mult}x {m['cagr']*100:.1f}%/{m['profit_factor']:.2f}/{m['max_dd']*100:.1f}%  ", end="")
    print()
    m = backtest(f, a, tf, start=START, end=OOS_END, risk=0.025, max_lev=10.0, max_bars_h=hold*24)
    dly = pd.Series(m["equity"], index=pd.to_datetime(m["dt"])).resample("1D").last().dropna().pct_change().fillna(0)
    b = bootstrap_dd(dly.to_numpy(), n=1500)
    print(f"  bootstrap DD median {b['dd_median']*100:.1f}%  5th pct {b['dd_p05']*100:.1f}%  "
          f"P(DD>20%) {b['p_dd_worse_than_20']*100:.0f}%")
    print(f"  yearly: " + " ".join(f"{y}:{v*100:+.0f}%" for y, v in m["yearly"].items()))
    # 1-minute execution grid
    H.EXEC_TF[0] = "fut_1m"
    m1 = backtest(f, a, tf, start=START, end=OOS_END, risk=0.025, max_lev=10.0, max_bars_h=hold*24)
    H.EXEC_TF[0] = "fut_15m"
    print(f"  1m execution: CAGR {m1['cagr']*100:.1f}% (vs {m['cagr']*100:.1f}%)  "
          f"DD {m1['max_dd']*100:.1f}% (vs {m['max_dd']*100:.1f}%)  PF {m1['profit_factor']:.2f}")
