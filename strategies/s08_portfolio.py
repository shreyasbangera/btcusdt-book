"""
S8 - Multi-Strategy Portfolio (MSP)

The single biggest lever left on Calmar is diversification: the delta-neutral
carry (S5) has almost no correlation with the directional books (S3/S4/S7).
Capital is split across sub-accounts, each sub-strategy compounds its own slice,
and the slices are rebalanced back to target weights monthly. The whole book is
then scaled by a single leverage knob so we can trace the CAGR/drawdown frontier.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_START, IS_END, OOS_END
from engine.data import load
import strategies.s07_smart as s07
import strategies.s03_ofi_swing as s03
import strategies.s04_advol as s04
import strategies.s05_carry as s05

def daily_from_equity(eq, dt):
    s = pd.Series(eq, index=pd.to_datetime(dt))
    d = s.resample("1D").last().dropna()
    return d.pct_change().fillna(0.0)

def sub_returns(start, end):
    """Daily return series of each sub-strategy, unlevered (risk 1%)."""
    out = {}
    fut4, f4 = panel("4h")
    f4m = f4[f4.dt >= "2021-01-03"].reset_index(drop=True)

    comp = s07.composite(f4m)
    a = s07.arrays(f4m, comp, thr=0.7, atr_stop=3.5, rr=2.5)
    m = backtest(f4m, a, "4h", start=start, end=end, risk=0.01, max_lev=5.0, max_bars_h=10*24)
    out["SMRD"] = daily_from_equity(m["equity"], m["dt"])

    a = s03.arrays(f4, thr=0.75, atr_stop=3.5, rr=2.5, trend_filter=True, flow="ofi24_resz")
    m = backtest(f4, a, "4h", start=start, end=end, risk=0.01, max_lev=5.0, max_bars_h=10*24)
    out["OFS"] = daily_from_equity(m["equity"], m["dt"])

    a = s04.arrays(f4, dc_n=40, adx_min=20, er_min=0.30, vol_adapt=False)
    m = backtest(f4, a, "4h", start=start, end=end, risk=0.01, max_lev=5.0, trail_after_r=1.0)
    out["AVT"] = daily_from_equity(m["equity"], m["dt"])

    r = s05.run(enter_thr=0.00008, allow_reverse=False, gross_lev=1.0, start=start, end=end)
    out["CARRY"] = daily_from_equity(r["equity"], r["dt"])
    return pd.DataFrame(out).fillna(0.0)

def portfolio(R, weights, lev=1.0, rebal="ME", eq0=10_000.0):
    """Each sleeve compounds its own slice; slices reset to target weights each month."""
    w = np.array([weights[c] for c in R.columns], float); w = w / w.sum()
    eq = eq0
    slices = eq * w
    curve = []
    period = pd.Series(R.index).dt.to_period("M").to_numpy()
    prev = period[0]
    for i, (dt, row) in enumerate(R.iterrows()):
        slices = slices * (1.0 + lev * row.to_numpy())
        eq = slices.sum()
        if eq <= 0:
            curve.append(0.0); continue
        if period[i] != prev:
            slices = eq * w; prev = period[i]
        curve.append(eq)
    e = np.array(curve)
    yrs = (R.index[-1] - R.index[0]).days / 365.25
    peak = np.maximum.accumulate(e); dd = e / peak - 1
    ret = pd.Series(e, index=R.index).pct_change().fillna(0)
    dp = pd.Series(e, index=R.index).diff().dropna()
    cagr = (e[-1] / eq0) ** (1 / yrs) - 1 if e[-1] > 0 else -1.0
    return dict(cagr=cagr, max_dd=float(dd.min()),
                sharpe=float(ret.mean()/ret.std()*np.sqrt(365.25)) if ret.std() > 0 else 0,
                calmar=float(cagr/abs(dd.min())) if dd.min() < 0 else np.inf,
                pf=float(dp[dp>0].sum()/-dp[dp<0].sum()) if (dp<0).any() else np.inf,
                equity=e, index=R.index)

if __name__ == "__main__":
    R_all = sub_returns(IS_START, OOS_END)
    print("sub-strategy daily-return correlation (2021-2026):")
    print(R_all.corr().round(3).to_string())
    print("\nannualised: " + "  ".join(
        f"{c}: {R_all[c].mean()*365.25*100:5.1f}% vol {R_all[c].std()*np.sqrt(365.25)*100:5.1f}%"
        for c in R_all.columns))
    inv = 1.0 / R_all.std().replace(0, np.nan)
    wsets = {
        "equal":     {c: 1.0 for c in R_all.columns},
        "riskparity": {c: float(inv[c]) for c in R_all.columns},
        "carry-tilt": {"SMRD": 1.0, "OFS": 0.7, "AVT": 1.0, "CARRY": 3.0},
    }
    print(f"\n{'weights':<13}{'lev':>5}{'CAGR':>9}{'MaxDD':>9}{'PF':>7}{'Sharpe':>8}{'Calmar':>8}")
    for wn, w in wsets.items():
        for lev in (1, 2, 3, 5, 8):
            p = portfolio(R_all, w, lev=lev)
            print(f"{wn:<13}{lev:>5}{p['cagr']*100:8.1f}%{p['max_dd']*100:8.1f}%{p['pf']:7.2f}{p['sharpe']:8.2f}{p['calmar']:8.2f}")
