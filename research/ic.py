"""Predictive-power diagnostics for candidate signals (before any backtest)."""
import numpy as np, pandas as pd
from scipy import stats

def fwd_ret(close, horizon):
    c = pd.Series(close)
    return (np.log(c.shift(-horizon)) - np.log(c)).to_numpy()

def ic_table(feat, close, horizons=(1,2,4,8,24), cols=None, mask=None):
    cols = cols or [c for c in feat.columns if c not in ("dt","close")]
    rows = []
    for h in horizons:
        y = fwd_ret(close, h)
        for c in cols:
            x = feat[c].to_numpy(float)
            m = np.isfinite(x) & np.isfinite(y)
            if mask is not None: m &= mask
            if m.sum() < 500: continue
            rho, p = stats.spearmanr(x[m], y[m])
            rows.append(dict(feature=c, h=h, ic=rho, p=p, n=int(m.sum())))
    return pd.DataFrame(rows)

def quantile_spread(x, close, horizon, q=5, mask=None):
    y = fwd_ret(close, horizon)
    x = np.asarray(x, float)
    m = np.isfinite(x) & np.isfinite(y)
    if mask is not None: m &= mask
    xs, ys = x[m], y[m]
    try:
        b = pd.qcut(pd.Series(xs), q, labels=False, duplicates="drop")
    except Exception:
        return None
    d = pd.DataFrame({"b": b, "y": ys})
    g = d.groupby("b").y.agg(["mean","count","std"])
    g["t"] = g["mean"]/(g["std"]/np.sqrt(g["count"]))
    return g

def newey_west_t(x, y, lags=None):
    """t-stat of the slope of y on x with Newey-West correction for overlap."""
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 100: return np.nan
    X = np.column_stack([np.ones_like(x), x])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    n, k = X.shape
    lags = lags or int(4*(n/100)**(2/9))
    S = (X*e[:,None]).T @ (X*e[:,None])
    for L in range(1, lags+1):
        w = 1 - L/(lags+1)
        G = (X[L:]*e[L:,None]).T @ (X[:-L]*e[:-L,None])
        S += w*(G+G.T)
    XtXi = np.linalg.inv(X.T@X)
    V = XtXi @ S @ XtXi
    return float(b[1]/np.sqrt(V[1,1]))
