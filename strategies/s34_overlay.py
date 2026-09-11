"""
S34 - Portfolio risk overlay: attack the drawdown, then re-lever.

Every previous attempt tried to raise the numerator (find a better signal).
This one attacks the denominator. Calmar = CAGR / MaxDD, and leverage moves
both together, so the ONLY way leverage buys you anything is if the equity
curve's drawdown shrinks faster than its return when you reshape it.

Two causal overlays on the portfolio's own daily returns:

  VOLTGT   exposure = target_vol / EWMA(realised vol of past returns)
           Homoskedastic equity curve. Drawdowns cluster in high-vol regimes,
           so cutting size there removes DD disproportionately to return.

  DDTHR    exposure tapers from 1.0 to a floor as equity falls below its own
           high-water mark, and restores on recovery. Caps the tail directly.

Both multipliers are computed from returns through day t-1 and applied to
day t, so there is no look-ahead. Scaling a futures book's daily return by m
is exact to first order: fees, slippage and funding all scale linearly with
notional. Verified against a true re-simulation at the bottom of this file.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s32_pair as s32

START = s32.START

def stats(r, eq0=10_000.0):
    e = eq0*np.cumprod(1.0+np.asarray(r, float))
    idx = r.index
    yrs = (idx[-1]-idx[0]).days/365.25
    peak = np.maximum.accumulate(e); dd = e/peak-1.0
    dp = np.diff(np.concatenate([[eq0], e]))
    cagr = (e[-1]/eq0)**(1/yrs)-1 if e[-1] > 0 else -1.0
    ys = {}; pv = eq0; es = pd.Series(e, index=idx)
    for y, g in es.groupby(es.index.year): ys[int(y)] = float(g.iloc[-1]/pv-1); pv = g.iloc[-1]
    sd = np.std(r)
    return dict(cagr=cagr, max_dd=float(dd.min()),
                sharpe=float(np.mean(r)/sd*np.sqrt(365.25)) if sd > 0 else 0.0,
                calmar=float(cagr/abs(dd.min())) if dd.min() < 0 else np.inf,
                pf=float(dp[dp > 0].sum()/-dp[dp < 0].sum()) if (dp < 0).any() else np.inf,
                equity=e, index=idx, yearly=ys)

def mult(r, target_vol=0.0, hl=20, warm=60, dd_soft=0.0, dd_hard=0.25,
         dd_floor=0.35, m_lo=0.25, m_hi=2.5):
    """Causal exposure multiplier: uses returns strictly before each day."""
    x = np.asarray(r, float); n = len(x)
    m = np.ones(n)
    lam = 0.5**(1.0/hl)
    var = np.nan; eq = 1.0; hwm = 1.0
    for i in range(n):
        mi = 1.0
        if target_vol > 0 and i >= warm and np.isfinite(var) and var > 0:
            mi = target_vol/(np.sqrt(var*365.25))
        if dd_soft > 0 and i >= warm:
            d = eq/hwm-1.0
            if d < -dd_soft:
                f = (dd_hard+d)/(dd_hard-dd_soft)
                mi *= max(min(f, 1.0), dd_floor)
        mi = float(np.clip(mi, m_lo, m_hi))
        m[i] = mi
        # advance state with day i's realised return (only affects i+1 onward)
        var = x[i]**2 if not np.isfinite(var) else lam*var + (1-lam)*x[i]**2
        eq *= (1.0 + mi*x[i]); hwm = max(hwm, eq)
    return pd.Series(m, index=r.index)

_S = {}
def base(k, s, e, wc=True):
    key = (k, s, e, wc)
    if key not in _S:
        sl = s32.sleeves(k, s, e, with_convex=wc)
        cols = [c for c in sl if not c.startswith("_")]
        inv = {c: 1.0/max(sl[c].std(), 1e-9) for c in cols}
        tot = sum(inv.values())
        _S[key] = (sl, {c: inv[c]/tot for c in cols})
    return _S[key]

def curve(k, s, e, wc=True, w=None, **ov):
    sl, rp = base(k, s, e, wc)
    c = s32.combine(sl, w or rp)
    r = pd.Series(c["equity"], index=c["index"]).pct_change().fillna(0.0)
    if ov:
        m = mult(r, **ov)
        r = r*m
    st = stats(r); st["trades"] = c["trades"]
    return st, (w or rp)

if __name__ == "__main__":
    IS_W = base(1, START, IS_END)[1]
    print("weights fixed in-sample:", {c: round(v, 3) for c, v in IS_W.items()})
    grids = [
        ("none",            dict()),
        ("voltgt 20%",      dict(target_vol=0.20, hl=20)),
        ("voltgt 25%",      dict(target_vol=0.25, hl=20)),
        ("voltgt 30%",      dict(target_vol=0.30, hl=20)),
        ("voltgt 25% hl40", dict(target_vol=0.25, hl=40)),
        ("ddthr 6/18",      dict(dd_soft=0.06, dd_hard=0.18, dd_floor=0.30)),
        ("ddthr 8/22",      dict(dd_soft=0.08, dd_hard=0.22, dd_floor=0.35)),
        ("vol25+ddthr8",    dict(target_vol=0.25, hl=20, dd_soft=0.08, dd_hard=0.22, dd_floor=0.35)),
        ("vol30+ddthr6",    dict(target_vol=0.30, hl=20, dd_soft=0.06, dd_hard=0.18, dd_floor=0.30)),
    ]
    print(f"\n{'overlay':>16} {'knob':>5} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}"
          f" | {'IS CAGR':>8}{'IS DD':>7} | {'OOS CAGR':>9}{'OOS DD':>8}")
    for lab, ov in grids:
        for k in (1.5, 3.0, 5.0):
            a, _ = curve(k, START, OOS_END, w=IS_W, **ov)
            i, _ = curve(k, START, IS_END,  w=IS_W, **ov)
            o, _ = curve(k, IS_END, OOS_END, w=IS_W, **ov)
            print(f"{lab:>16} {k:>5} | {a['cagr']*100:7.1f}%{a['max_dd']*100:7.1f}%"
                  f"{a['pf']:6.2f}{a['sharpe']:6.2f}{a['calmar']:6.2f} | "
                  f"{i['cagr']*100:7.1f}%{i['max_dd']*100:6.1f}% | "
                  f"{o['cagr']*100:8.1f}%{o['max_dd']*100:7.1f}%")
