"""
S36 - Implied-volatility momentum   [BTCUSDT perp only]

A genuinely new input class. Everything else in this study is REALISED: prices,
taker flow, open interest, positioning, funding. Binance also publishes BVOL,
a 30-day forward-looking implied volatility index for BTC - the market's PRICE
of future risk rather than a measurement of past risk.

    iv_mom      3-day percentage change in BVOL, z-scored on a 30-day window
    iv_mom_res  the same, orthogonalised to 3-day PRICE momentum with
                coefficients refit monthly on an expanding window of strictly
                past data (the same construction as S31's ofi6_res)

Why the residual matters: raw IV momentum could just be a price-momentum proxy.
It is not - the two correlate -0.10, price momentum's own IC is NEGATIVE over
this window, and stripping it out RAISES the IC rather than lowering it. What
is left is the options market repricing risk before the perp moves.

    stability:  IS +0.083 -> OOS +0.090 at a 1-day horizon (12h bars)
    economics:  decile spread +44 bps at h=1d against a 16 bps round turn

Sample caveat, stated up front: BVOL only exists from 2023-06-20, so this book
has 3.2 years of history where the others have 5.7.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs

START = "2023-06-21"

_C = {}
def ivpanel(tf="12h"):
    if tf in _C: return _C[tf]
    fut, f = panel(tf)
    bv = pd.read_parquet(str(_P.DATA / "bvol_1m.parquet"))
    bv["dt"] = pd.to_datetime(bv.dt, utc=True).astype("datetime64[ns, UTC]")
    iv = bv.set_index("dt")["iv"].resample(tf).last().dropna().rename("iv")
    f["dt"] = pd.to_datetime(f.dt, utc=True).astype("datetime64[ns, UTC]")
    f = f.merge(iv.reset_index(), on="dt", how="left")
    f = f[f.dt >= START].reset_index(drop=True)
    f["iv"] = f.iv.ffill(limit=4)
    bd = int(pd.Timedelta("1D") / pd.Timedelta(tf))
    c = f.close.to_numpy(float); n = len(c)
    x = zs(pd.Series(f.iv.to_numpy(float)).pct_change(3 * bd).to_numpy(), 30 * bd)
    pm = zs(pd.Series(np.log(c)).diff(3 * bd).to_numpy(), 30 * bd)
    res = np.full(n, np.nan); good = np.isfinite(x) & np.isfinite(pm)
    warm, step, coef = 90 * bd, 30 * bd, None
    for i0 in range(warm, n, step):
        hist = good.copy(); hist[i0:] = False          # strictly past
        if hist.sum() > 200:
            A = np.column_stack([np.ones(hist.sum()), pm[hist]])
            coef = np.linalg.lstsq(A, x[hist], rcond=None)[0]
        if coef is not None:
            j1 = min(i0 + step, n)
            res[i0:j1] = x[i0:j1] - (coef[0] + coef[1] * pm[i0:j1])
    f["iv_mom"] = x; f["iv_mom_res"] = res
    _C[tf] = f
    return f

def signal(f, use_res=True, zwin=120):
    v = f.iv_mom_res if use_res else f.iv_mom
    return zs(v.to_numpy(float), zwin)

def arrays(f, s, thr=1.0, atr_stop=3.0, rr=2.0, long_only=False):
    a = f.atr14.to_numpy()
    e = np.where(s > thr, 1.0, 0.0) if long_only else \
        np.where(s > thr, 1.0, np.where(s < -thr, -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=atr_stop * a,
                tp=atr_stop * rr * a, exit=np.zeros(len(f)))

def show(lab, m):
    print(f"{lab:>36} | CAGR {m['cagr']*100:7.1f}% DD {m['max_dd']*100:6.1f}% "
          f"PF {m['profit_factor']:5.2f} N {m['trades']:4d} WR {m['win_rate']*100:4.1f}% "
          f"Shp {m['sharpe']:5.2f} Clm {m['calmar']:5.2f}")

if __name__ == "__main__":
    for tf in ("12h", "4h"):
        f = ivpanel(tf)
        print(f"\n===== {tf}  {len(f)} bars  {f.dt.min().date()} -> {f.dt.max().date()}"
              f"   IS ends {IS_END}")
        for use_res in (True, False):
            s = signal(f, use_res=use_res)
            for thr in (0.7, 1.0, 1.4):
                for stp, rr in ((3.0, 2.0), (3.5, 2.5), (2.5, 1.5)):
                    kw = dict(risk=0.02, max_lev=10.0, max_bars_h=7 * 24)
                    a = arrays(f, s, thr=thr, atr_stop=stp, rr=rr)
                    A = backtest(f, a, tf, start=START, end=OOS_END, **kw)
                    I = backtest(f, a, tf, start=START, end=IS_END, **kw)
                    O = backtest(f, a, tf, start=IS_END, end=OOS_END, **kw)
                    tag = "res" if use_res else "raw"
                    print(f"{tag} thr{thr} {stp}x{rr}".rjust(20) +
                          f" | ALL {A['cagr']*100:6.1f}% DD{A['max_dd']*100:6.1f}% "
                          f"PF{A['profit_factor']:5.2f} N{A['trades']:4d} Shp{A['sharpe']:5.2f}"
                          f"  | IS {I['cagr']*100:6.1f}% PF{I['profit_factor']:5.2f}"
                          f"  | OOS {O['cagr']*100:6.1f}% PF{O['profit_factor']:5.2f} N{O['trades']:4d}")
