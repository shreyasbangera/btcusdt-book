"""
S9 - Multi-Strategy Portfolio, honest leverage (MSP-R)

S8 scaled each sleeve's RETURN series by a leverage knob. That is wrong for the
carry sleeve, whose cost of leverage (USDT borrow on the spot leg) is not linear
in the return. Here every sleeve is RE-SIMULATED at its actual size:

  * directional sleeves: `risk` per trade is raised, so position size, stop
    distance, fees, slippage and the exchange leverage cap all respond properly;
  * carry sleeve: `gross_lev` is raised, so the 8% APR USDT borrow on the
    levered spot leg is charged in full.

Capital is split across four sub-accounts and rebalanced to target weights
monthly. Sleeve sizes are set so each contributes comparable risk.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_START, IS_END, OOS_END
import strategies.s07_smart as s07
import strategies.s03_ofi_swing as s03
import strategies.s04_advol as s04
import strategies.s05_carry as s05

MAX_LEV_DIR = 10.0        # exchange leverage cap used for the directional books
CARRY_GROSS_CAP = 6.0     # cap on gross notional of the cash-and-carry sleeve

_p4 = None
def _panels():
    global _p4
    if _p4 is None:
        fut4, f4 = panel("4h")
        _p4 = (fut4, f4, f4[f4.dt >= "2021-01-03"].reset_index(drop=True))
    return _p4

def daily(eq, dt):
    s = pd.Series(eq, index=pd.to_datetime(dt))
    return s.resample("1D").last().dropna().pct_change().fillna(0.0)

def sleeves(k, start, end):
    """k = size knob. Returns daily return series per sleeve at true size."""
    fut4, f4, f4m = _panels()
    out = {}
    comp = s07.composite(f4m)
    a = s07.arrays(f4m, comp, thr=0.7, atr_stop=3.5, rr=2.5)
    m = backtest(f4m, a, "4h", start=start, end=end, risk=min(0.01*k, 0.12),
                 max_lev=MAX_LEV_DIR, max_bars_h=10*24)
    out["SMRD"] = daily(m["equity"], m["dt"]); out["_SMRD_n"] = m["trades"]

    a = s03.arrays(f4, thr=0.75, atr_stop=3.5, rr=2.5, trend_filter=True, flow="ofi24_resz")
    m = backtest(f4, a, "4h", start=start, end=end, risk=min(0.013*k, 0.15),
                 max_lev=MAX_LEV_DIR, max_bars_h=10*24)
    out["OFS"] = daily(m["equity"], m["dt"]); out["_OFS_n"] = m["trades"]

    a = s04.arrays(f4, dc_n=40, adx_min=20, er_min=0.30, vol_adapt=False)
    m = backtest(f4, a, "4h", start=start, end=end, risk=min(0.007*k, 0.09),
                 max_lev=MAX_LEV_DIR, trail_after_r=1.0)
    out["AVT"] = daily(m["equity"], m["dt"]); out["_AVT_n"] = m["trades"]

    r = s05.run(enter_thr=0.00008, allow_reverse=False,
                gross_lev=min(1.0 + 0.55*(k-1), CARRY_GROSS_CAP), start=start, end=end)
    out["CARRY"] = daily(r["equity"], r["dt"]); out["_CARRY_n"] = r["trades"]
    return out

def combine(sl, w=None, eq0=10_000.0):
    cols = [c for c in sl if not c.startswith("_")]
    R = pd.DataFrame({c: sl[c] for c in cols}).fillna(0.0)
    w = w or {c: 1.0 for c in cols}
    wv = np.array([w[c] for c in cols], float); wv /= wv.sum()
    slices = eq0 * wv; curve = []
    per = pd.Series(R.index).dt.to_period("M").to_numpy(); prev = per[0]
    for i in range(len(R)):
        slices = slices * (1.0 + R.iloc[i].to_numpy())
        e = slices.sum()
        if e <= 0:
            curve.append(0.0); continue
        if per[i] != prev:
            slices = e * wv; prev = per[i]
        curve.append(e)
    e = np.array(curve)
    yrs = (R.index[-1] - R.index[0]).days / 365.25
    peak = np.maximum.accumulate(e); dd = e/peak - 1
    ret = pd.Series(e, index=R.index).pct_change().fillna(0)
    dp = pd.Series(e, index=R.index).diff().dropna()
    cagr = (e[-1]/eq0)**(1/yrs) - 1 if e[-1] > 0 else -1.0
    ntr = sum(sl[f"_{c}_n"] for c in cols)
    yearly = {}; prevv = eq0
    es = pd.Series(e, index=R.index)
    for y, g in es.groupby(es.index.year):
        yearly[int(y)] = float(g.iloc[-1]/prevv - 1); prevv = g.iloc[-1]
    return dict(cagr=cagr, max_dd=float(dd.min()),
                sharpe=float(ret.mean()/ret.std()*np.sqrt(365.25)) if ret.std()>0 else 0,
                calmar=float(cagr/abs(dd.min())) if dd.min()<0 else np.inf,
                pf=float(dp[dp>0].sum()/-dp[dp<0].sum()) if (dp<0).any() else np.inf,
                win_rate=float((dp>0).mean()), trades=int(ntr),
                equity=e, index=R.index, yearly=yearly, R=R)

if __name__ == "__main__":
    print(f"{'knob':>5}{'CAGR':>9}{'MaxDD':>9}{'PF':>7}{'Sharpe':>8}{'Calmar':>8}{'N':>7}   per-year")
    for k in (1, 2, 4, 6, 8, 10, 12, 14):
        sl = sleeves(k, IS_START, OOS_END)
        p = combine(sl)
        y = " ".join(f"{yy}:{v*100:+.0f}%" for yy, v in p["yearly"].items())
        print(f"{k:>5}{p['cagr']*100:8.1f}%{p['max_dd']*100:8.1f}%{p['pf']:7.2f}"
              f"{p['sharpe']:8.2f}{p['calmar']:8.2f}{p['trades']:7d}   {y}")
