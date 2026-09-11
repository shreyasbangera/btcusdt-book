"""
Continuous-weight simulator (for volatility-targeted / risk-managed exposure).

w[t] is the TARGET notional exposure as a multiple of equity, decided from
information available at the close of bar t and applied from bar t+1 onward.
Turnover |w[t]-w[t-1]| is charged fees+slippage. Real funding is charged on the
open notional at each settlement. A "trade" is counted each time the sign of the
exposure changes or the position returns to flat, so the trade count is
comparable with the discrete strategies.
"""
import numpy as np, pandas as pd
from .data import load


def simulate(df, w, fee_bps=5.0, slip_bps=3.0, eq0=10_000.0, real_funding=True,
             max_w=5.0, funding_df=None):
    d = df.reset_index(drop=True)
    c = d.close.to_numpy(float)
    n = len(d)
    w = np.nan_to_num(np.asarray(w, float))
    w = np.clip(w, -max_w, max_w)
    w_eff = np.r_[0.0, w[:-1]]                    # applied from the NEXT bar
    r = np.r_[0.0, np.diff(np.log(c))]            # bar log-return
    simple = np.expm1(r)

    fund = np.zeros(n)
    if real_funding:
        fr = funding_df if funding_df is not None else load("funding")
        idx = np.searchsorted(d.dt.to_numpy(), fr.dt.to_numpy())
        ok = idx < n
        fund[idx[ok]] = fr.rate.to_numpy()[ok]

    cost_rate = (fee_bps + slip_bps) / 1e4
    turn = np.abs(np.diff(np.r_[0.0, w_eff]))
    eq = np.empty(n); e = eq0
    for i in range(n):
        e *= (1.0 + w_eff[i] * simple[i])
        e -= e * turn[i] * cost_rate
        e -= e * w_eff[i] * fund[i]               # long pays a positive rate
        if e <= 0:
            eq[i:] = 0.0; e = 0.0; break
        eq[i] = e
    eq = pd.Series(eq).replace(0.0, np.nan).ffill().fillna(eq0).to_numpy()

    yrs = (d.dt.iloc[-1] - d.dt.iloc[0]).total_seconds() / (365.25 * 24 * 3600)
    peak = np.maximum.accumulate(eq); dd = eq / peak - 1.0
    s = np.sign(w_eff)
    ntr = int((np.diff(s) != 0).sum())
    daily = pd.Series(eq, index=d.dt).resample("1D").last().dropna().pct_change().fillna(0)
    # profit factor over daily P&L
    dpnl = pd.Series(eq, index=d.dt).resample("1D").last().dropna().diff().dropna()
    gp = dpnl[dpnl > 0].sum(); gl = -dpnl[dpnl < 0].sum()
    cagr = (eq[-1] / eq0) ** (1 / yrs) - 1 if eq[-1] > 0 else -1.0
    yearly = {}; prev = eq0
    es = pd.Series(eq, index=d.dt)
    for y, g in es.groupby(es.index.year):
        yearly[int(y)] = float(g.iloc[-1] / prev - 1); prev = g.iloc[-1]
    return dict(cagr=float(cagr), max_dd=float(dd.min()),
                profit_factor=float(gp / gl) if gl > 0 else float("inf"),
                trades=ntr, win_rate=float((dpnl > 0).mean()),
                sharpe=float(daily.mean() / daily.std() * np.sqrt(365.25)) if daily.std() > 0 else 0.0,
                calmar=float(cagr / abs(dd.min())) if dd.min() < 0 else float("inf"),
                exposure=float((np.abs(w_eff) > 1e-9).mean()),
                avg_gross=float(np.abs(w_eff).mean()),
                turnover_yr=float(turn.sum() / yrs),
                equity=eq, yearly=yearly, dt=d.dt.to_numpy(), years=float(yrs))
