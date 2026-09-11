"""Robustness diagnostics: cost stress, bootstrap drawdown, parameter neighbourhoods."""
import numpy as np, pandas as pd

def bootstrap_dd(daily_ret, n=2000, seed=0, block=5):
    """Stationary block bootstrap of the daily return series -> distribution of
    max drawdown and CAGR. Blocks preserve short-horizon autocorrelation."""
    rng = np.random.default_rng(seed)
    r = np.asarray(daily_ret, float)
    r = r[np.isfinite(r)]
    T = len(r)
    dds = np.empty(n); cgs = np.empty(n)
    nb = int(np.ceil(T / block))
    for i in range(n):
        starts = rng.integers(0, T - block, nb)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:T]
        e = np.cumprod(1 + r[idx])
        peak = np.maximum.accumulate(e)
        dds[i] = (e / peak - 1).min()
        cgs[i] = e[-1] ** (365.25 / T) - 1
    return dict(dd_median=float(np.median(dds)), dd_p05=float(np.percentile(dds, 5)),
                dd_p95=float(np.percentile(dds, 95)),
                cagr_median=float(np.median(cgs)), cagr_p05=float(np.percentile(cgs, 5)),
                cagr_p95=float(np.percentile(cgs, 95)),
                p_dd_worse_than_20=float((dds < -0.20).mean()))

def summarise(eq, index, eq0=10_000.0):
    e = np.asarray(eq, float)
    yrs = (index[-1] - index[0]).days / 365.25
    peak = np.maximum.accumulate(e); dd = e / peak - 1
    ret = pd.Series(e, index=index).pct_change().fillna(0)
    dp = pd.Series(e, index=index).diff().dropna()
    cagr = (e[-1] / eq0) ** (1 / yrs) - 1 if e[-1] > 0 else -1.0
    return dict(cagr=float(cagr), max_dd=float(dd.min()),
                sharpe=float(ret.mean() / ret.std() * np.sqrt(365.25)) if ret.std() > 0 else 0.0,
                calmar=float(cagr / abs(dd.min())) if dd.min() < 0 else float("inf"),
                pf=float(dp[dp > 0].sum() / -dp[dp < 0].sum()) if (dp < 0).any() else float("inf"))
