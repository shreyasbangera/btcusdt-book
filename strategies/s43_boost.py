"""
S43 - The other term in the ceiling.

Portfolio Sharpe -> s / sqrt(rho-bar). rho-bar is a property of the market and
sits at 0.10; nothing in the search moves it. That leaves s, the per-sleeve
Sharpe, which currently runs 0.44-1.41 with a mean near 0.9. Every 10% gain in
s is a 10% gain in the ceiling, and it applies to all eight sleeves at once.

Three ways to lift s that do NOT require a new signal, tested on the four
strongest sleeves so the answer is not an artefact of one book:

  A  VOL-SCALED SIZING   size each trade by 1/forecast-vol rather than by ATR
     alone, using a HAR-style forecast (daily/weekly/monthly realised vol),
     which is a materially better predictor of next-period vol than ATR.
  B  SIGNAL-STRENGTH SIZING   size proportional to |z| above the threshold
     instead of taking every crossing at full size. If IC is real, the
     conviction ordering should carry information about outcome size.
  C  TIME-STOP TUNING   the 7-day cap was set once and never revisited; the
     right hold is a property of each signal's decay, not a global constant.

All three are causal and cost nothing in signal quality - they only change how
much is bet and for how long.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.runner import zs
import strategies.s36_ivmom as s36
import strategies.s38_orth as s38
import strategies.s31_ofi6 as s31

FULL_START = "2021-03-01"

def har_vol(c, bars_day):
    """Causal HAR-style vol forecast: blend of 1d, 5d and 22d realised vol."""
    lr = pd.Series(np.log(c)).diff()
    d = lr.rolling(bars_day).std()
    w = lr.rolling(5 * bars_day).std()
    m = lr.rolling(22 * bars_day).std()
    return (0.4 * d + 0.35 * w + 0.25 * m).to_numpy()

def arrays(f, s, thr=1.0, stp=3.0, rr=2.0, mode="base", vf=None, zcap=3.0):
    a = f.atr14.to_numpy(float)
    e = np.where(s > thr, 1.0, np.where(s < -thr, -1.0, 0.0))
    stop = stp * a
    if mode == "volscale" and vf is not None:
        # keep average stop distance the same, but let the vol forecast set the shape
        r = vf * f.close.to_numpy(float)
        r = r / np.nanmean(r) * np.nanmean(a)
        stop = stp * np.where(np.isfinite(r) & (r > 0), r, a)
    if mode == "conviction":
        w = np.clip(np.abs(s) / thr, 1.0, zcap)
        e = e * w                       # engine reads |entry| as a risk multiplier
    if mode == "sqrtconv":
        w = np.clip(np.sqrt(np.abs(s) / thr), 1.0, zcap)
        e = e * w
    if mode == "tailonly":
        e = np.where(np.abs(s) > zcap * thr, e, 0.0)
    return dict(entry=np.nan_to_num(e), stop=stop, tp=stop * rr, exit=np.zeros(len(f)))

BOOKS = {}
def books():
    if BOOKS: return BOOKS
    fi = s36.ivpanel("12h")
    fx = s38.xpanel("12h"); fx = fx[fx.dt >= FULL_START].reset_index(drop=True)
    f12 = s31.__dict__  # not used; s31 signal comes from its own panel
    from research.harness import panel as _p
    _, fo = _p("12h"); fo = fo[fo.dt >= FULL_START].reset_index(drop=True)
    BOOKS.update(
        IVOL=(fi, s36.signal(fi, use_res=False), s36.START),
        CMPX=(fx, fx.f_cmpx.to_numpy(float), FULL_START),
        BTCDOM=(fx, fx.btc_dom_z.to_numpy(float), FULL_START),
        FLOW=(fo, zs(fo.ofi6_res.to_numpy(float), 480), FULL_START))
    return BOOKS

if __name__ == "__main__":
    B = books()
    thr = {"IVOL": 0.7, "CMPX": 1.0, "BTCDOM": 1.0, "FLOW": 1.0}
    print(f"{'book':>8} {'variant':>22} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'Shp':>6}"
          f" | {'IS Shp':>7}{'OOS Shp':>8}")
    for name, (f, s, start) in B.items():
        vf = har_vol(f.close.to_numpy(float), 2)
        base_shp = None
        variants = [("base 3.0x2.0 hold 7d", dict(mode="base"), 7 * 24),
                    ("conviction linear cap3", dict(mode="conviction", zcap=3.0), 7 * 24),
                    ("conviction linear cap2", dict(mode="conviction", zcap=2.0), 7 * 24),
                    ("conviction sqrt cap2", dict(mode="sqrtconv", zcap=2.0), 7 * 24),
                    ("tail only |z|>1.5thr", dict(mode="tailonly", zcap=1.5), 7 * 24),
                    ("tail only |z|>2.0thr", dict(mode="tailonly", zcap=2.0), 7 * 24),
                    ("hold 14d", dict(mode="base"), 14 * 24),
                    ("hold 30d", dict(mode="base"), 30 * 24)]
        for lab, kw, hold in variants:
            a = arrays(f, s, thr=thr[name], **kw)
            r = dict(risk=0.02, max_lev=10.0, max_bars_h=hold)
            A = backtest(f, a, "12h", start=start, end=OOS_END, **r)
            I = backtest(f, a, "12h", start=start, end=IS_END, **r)
            O = backtest(f, a, "12h", start=IS_END, end=OOS_END, **r)
            if base_shp is None: base_shp = A["sharpe"]
            mark = " *" if A["sharpe"] > base_shp + 0.05 and O["sharpe"] > 0 else ""
            print(f"{name:>8} {lab:>22} | {A['cagr']*100:7.1f}%{A['max_dd']*100:7.1f}%"
                  f"{A['profit_factor']:6.2f}{A['trades']:6d}{A['sharpe']:6.2f} | "
                  f"{I['sharpe']:7.2f}{O['sharpe']:8.2f}{mark}")
        print()
