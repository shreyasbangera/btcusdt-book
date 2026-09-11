"""Indicator library. Every function returns values aligned to the bar index,
using only information available up to and including that bar (no look-ahead)."""
import numpy as np, pandas as pd

def ema(s, n):    return pd.Series(s).ewm(span=n, adjust=False).mean().to_numpy()
def sma(s, n):    return pd.Series(s).rolling(n).mean().to_numpy()
def stdev(s, n):  return pd.Series(s).rolling(n).std(ddof=0).to_numpy()

def rma(s, n):
    return pd.Series(s).ewm(alpha=1.0/n, adjust=False).mean().to_numpy()

def true_range(h, l, c):
    pc = pd.Series(c).shift(1).to_numpy()
    return np.nanmax(np.vstack([h-l, np.abs(h-pc), np.abs(l-pc)]), axis=0)

def atr(h, l, c, n=14):
    return rma(true_range(h, l, c), n)

def rsi(c, n=14):
    d = pd.Series(c).diff()
    up = rma(d.clip(lower=0).fillna(0).to_numpy(), n)
    dn = rma((-d.clip(upper=0)).fillna(0).to_numpy(), n)
    rs = np.divide(up, dn, out=np.full_like(up, np.inf), where=dn > 0)
    return 100 - 100/(1+rs)

def adx(h, l, c, n=14):
    up = pd.Series(h).diff(); dn = -pd.Series(l).diff()
    plus  = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = rma(true_range(h, l, c), n)
    pdi = 100 * rma(plus, n) / np.where(tr == 0, np.nan, tr)
    mdi = 100 * rma(minus, n) / np.where(tr == 0, np.nan, tr)
    dx = 100 * np.abs(pdi - mdi) / np.where((pdi+mdi) == 0, np.nan, pdi+mdi)
    return rma(np.nan_to_num(dx), n), pdi, mdi

def bbands(c, n=20, k=2.0):
    m = sma(c, n); s = stdev(c, n)
    return m, m + k*s, m - k*s, np.divide(2*k*s, m, out=np.zeros_like(m), where=m > 0)

def keltner(c, h, l, n=20, k=1.5):
    m = ema(c, n); a = atr(h, l, c, n)
    return m, m + k*a, m - k*a

def donchian(h, l, n=20):
    """Channel of the n bars ENDING at the previous bar (shifted -> no look-ahead
    when used as a breakout level for the current bar)."""
    hh = pd.Series(h).rolling(n).max().shift(1).to_numpy()
    ll = pd.Series(l).rolling(n).min().shift(1).to_numpy()
    return hh, ll

def macd(c, f=12, s=26, sig=9):
    m = ema(c, f) - ema(c, s)
    sg = ema(m, sig)
    return m, sg, m - sg

def zscore(s, n):
    x = pd.Series(s)
    return ((x - x.rolling(n).mean()) / x.rolling(n).std(ddof=0)).to_numpy()

def rolling_rank(s, n):
    """Percentile rank of the current value within the trailing n-bar window."""
    return pd.Series(s).rolling(n).rank(pct=True).to_numpy()

def realized_vol(c, n):
    r = pd.Series(np.log(c)).diff()
    return r.rolling(n).std(ddof=0).to_numpy()

def hurst_rs(c, n=100):
    """Rolling simplified Hurst exponent via variance-ratio on log returns."""
    lr = pd.Series(np.log(c)).diff().fillna(0)
    v1 = lr.rolling(n).var(ddof=0)
    v2 = lr.rolling(n).sum().rolling(1).mean()  # placeholder
    v_k = lr.rolling(n).apply(lambda x: np.var(np.add.reduceat(x, np.arange(0, len(x), 5))[:-1]), raw=True)
    with np.errstate(all="ignore"):
        h = 0.5 * np.log(v_k / (v1 * 5)) / np.log(5) + 0.5
    return h.to_numpy()

def supertrend(h, l, c, n=10, mult=3.0):
    a = atr(h, l, c, n); hl2 = (h + l) / 2
    ub = hl2 + mult*a; lb = hl2 - mult*a
    fub = np.copy(ub); flb = np.copy(lb); dirn = np.ones(len(c))
    for i in range(1, len(c)):
        fub[i] = ub[i] if (ub[i] < fub[i-1] or c[i-1] > fub[i-1]) else fub[i-1]
        flb[i] = lb[i] if (lb[i] > flb[i-1] or c[i-1] < flb[i-1]) else flb[i-1]
        if c[i] > fub[i-1]:   dirn[i] = 1
        elif c[i] < flb[i-1]: dirn[i] = -1
        else:                 dirn[i] = dirn[i-1]
    return dirn, np.where(dirn == 1, flb, fub)

def vwap_session(dt, h, l, c, v, freq="D"):
    tp = (h + l + c) / 3.0
    g = pd.Series(pd.to_datetime(dt)).dt.to_period(freq)
    df = pd.DataFrame({"tp": tp, "v": v, "g": g})
    cum_pv = df.groupby("g")["v"].cumsum()
    cum_tpv = (df.tp * df.v).groupby(df.g).cumsum()
    return (cum_tpv / cum_pv.replace(0, np.nan)).to_numpy()
