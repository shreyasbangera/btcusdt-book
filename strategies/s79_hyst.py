"""
S79 - Two untested corners: slower decisions, and per-signal hysteresis.

S55 swept decision frequencies FASTER than 12h (6h, 4h, 2h, 1h) and found a
clean monotone collapse.  It never tested SLOWER.  Fewer bets is the wrong
direction for Sharpe = IC x sqrt(N), but only if IC per bet stays flat - and a
slower grid averages more flow into each reading, so it might not.

Second: every signal contributes nothing until |z| passes its threshold, and
stops contributing the moment it falls back through the same level.  A signal
oscillating around 1.0 therefore switches on and off repeatedly, moving the net
and churning the position.  HYSTERESIS - enter a signal at |z| > thr, keep it
until |z| < thr x k - removes that without the dead-band that failed in S71,
because the dead band moved the NET's exit while this moves each signal's own.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs
import strategies.s45_single as S
import strategies.s46_net as S46
import strategies.s07_smart as s07
import strategies.s38_orth as s38

def hyst_unit(z, thr, k=1.0, cap=S.CAP):
    """|z| > thr turns the signal on; it stays on until |z| < thr*k."""
    z = np.asarray(z, float)
    on = np.zeros(len(z)); side = np.zeros(len(z))
    cur = 0.0
    for i in range(len(z)):
        v = z[i]
        if not np.isfinite(v):
            on[i] = 0.0; side[i] = cur; continue
        if cur == 0.0:
            if v > thr: cur = 1.0
            elif v < -thr: cur = -1.0
        else:
            if abs(v) < thr * k or np.sign(v) != cur:
                cur = 1.0 if v > thr else (-1.0 if v < -thr else 0.0)
        side[i] = cur
        on[i] = abs(cur)
    mag = np.clip(np.abs(z) / thr, 1.0, cap)
    return np.nan_to_num(side * mag * on)

def net_h(g, k=1.0, exp=2.5, cap=3.0):
    U = [hyst_unit(g[f"s_{n}"].to_numpy(float), S.THR[n], k) for n in S46.LONG]
    v = np.column_stack(U) @ (np.ones(len(U)) / len(U))
    nz = np.abs(v) > 0
    if nz.sum() < 50 or exp == 1.0: return v
    u = np.sign(v) * np.abs(v) ** exp
    return np.sign(u) * np.minimum(np.abs(u) * (np.abs(v[nz]).mean() /
                                   max(np.abs(u[nz]).mean(), 1e-12)), cap)

def go(g, v, tag, risk=0.08, tf="12h", stp=2.5, rr=3.0, hold=14, start=None):
    a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(v), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(v)) <= 0.0).astype(float))
    st = start or str(g.dt.iloc[0].date())
    A = backtest(g, arr, tf, start=st, end=OOS_END, risk=risk, max_lev=10.0, max_bars_h=hold*24)
    O = backtest(g, arr, tf, start=IS_END, end=OOS_END, risk=risk, max_lev=10.0, max_bars_h=hold*24)
    r = pd.Series(A["equity"], index=pd.to_datetime(A["dt"])).resample("1D").last(
        ).dropna().pct_change().fillna(0).to_numpy()
    b = bootstrap_dd(r, n=1500)
    print(f"{tag:>30}{risk*100:5.0f}% | CAGR {A['cagr']*100:7.1f}%  DD {A['max_dd']*100:6.1f}%  "
          f"PF {A['profit_factor']:5.2f}  N {A['trades']:4d}  Shp {A['sharpe']:5.2f}  "
          f"Clm {A['calmar']:5.2f} | OOS {O['cagr']*100:6.1f}%  med {b['dd_median']*100:6.1f}%"
          f"  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")

def slow_panel(tf):
    """Rebuild the five signals on a slower grid, windows rescaled to the same span."""
    per_day = int(pd.Timedelta("1D") / pd.Timedelta(tf)) or 1
    k = per_day / 2.0
    _, f = panel(tf); f["dt"] = pd.to_datetime(f.dt, utc=True).astype("datetime64[ns, UTC]")
    xf = s38.xpanel("12h").set_index("dt")
    f = f.merge(xf[["cm_px","btc_dom_z"]].resample(tf).last().reset_index(), on="dt", how="left")
    _, f4 = panel("4h"); f4["dt"] = pd.to_datetime(f4.dt, utc=True).astype("datetime64[ns, UTC]")
    po = pd.DataFrame({"dt": f4.dt, "posn": s07.composite(f4)}).set_index("dt")
    f = f.merge(po.resample(tf).last().reset_index(), on="dt", how="left")
    f = f[f.dt >= S.FULL_START].reset_index(drop=True)
    w = lambda n: max(int(round(n * k)), 8)
    c = f.close.to_numpy(float)
    f["s_flow"] = zs(f.ofi6_res.to_numpy(float), w(480))
    f["s_cmpx"] = zs(pd.Series(np.log(f.cm_px.to_numpy(float)/c)).diff(max(int(6/k),1)).to_numpy(), w(120))
    f["s_btcdom"] = f.btc_dom_z
    f["s_fundz"] = -zs(f.fund.to_numpy(float), w(240))
    f["s_posn"] = f.posn
    return f

if __name__ == "__main__":
    g = S.grid(S.FULL_START)
    print("--- per-signal hysteresis (k = the fraction of threshold a signal must fall below)\n")
    for k in (1.0, 0.8, 0.6, 0.4):
        go(g, net_h(g, k), f"hysteresis k={k}")
    print("\n--- slower decision grids (12h is the incumbent)\n")
    for tf in ("12h", "1d", "2d"):
        try:
            f = slow_panel(tf)
            hold = 14 if tf == "12h" else (21 if tf == "1d" else 40)
            U = [S.unit(f, n) for n in S46.LONG]
            v = np.column_stack(U) @ (np.ones(len(U))/len(U))
            nz = np.abs(v) > 0
            u = np.sign(v)*np.abs(v)**2.5
            v = np.sign(u)*np.minimum(np.abs(u)*(np.abs(v[nz]).mean()/max(np.abs(u[nz]).mean(),1e-12)), 3.0)
            go(f, v, f"decisions every {tf}", tf=tf, hold=hold)
        except Exception as e:
            print(f"  {tf}: {type(e).__name__} {e}")
