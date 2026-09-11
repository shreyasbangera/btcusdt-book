"""
S45 - One account, one position.

Everything up to here ran the sleeves as separate sub-accounts that rebalanced
monthly. That is not tradable in a single account, so this rebuilds the same
idea as ONE strategy: every signal is reduced to a single net target on one
12h decision grid, and the account holds at most one BTCUSDT position at a time,
with one stop and one target.

    net = sum_i w_i * clip(z_i / thr_i, -cap, +cap)   over signals that agree
          or disagree; opposing signals cancel before anything is traded.

This is a real change, not a presentational one, and it can go either way:

  it should HELP  - opposing signals net out instead of paying two round turns
                    to hold offsetting positions, and one stop on the net
                    position is cheaper than seven stops on seven of them.
  it should HURT  - each sleeve loses its own stop and its own exit clock, and
                    blending has degraded the strongest signal three times in
                    this study (S2, the breadth blend, the S30 composite).

The difference this time is that those blends averaged CORRELATED signals.
These correlate 0.10 on average. Averaging orthogonal signals is what a
multi-factor model does; averaging correlated ones is just noise reduction on
a single view. Measured below rather than assumed.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs
import strategies.s36_ivmom as s36
import strategies.s38_orth as s38
import strategies.s07_smart as s07

FULL_START = "2021-03-01"; BV_START = "2023-06-21"
CAP = 2.0

def grid(start):
    """One 12h decision panel carrying every signal, aligned by timestamp."""
    _, f = panel("12h")
    f["dt"] = pd.to_datetime(f.dt, utc=True).astype("datetime64[ns, UTC]")
    xf = s38.xpanel("12h")
    iv = s36.ivpanel("12h")[["dt", "iv_mom"]]
    _, f4 = panel("4h")
    f4["dt"] = pd.to_datetime(f4.dt, utc=True).astype("datetime64[ns, UTC]")
    posn = pd.DataFrame({"dt": f4.dt, "posn": s07.composite(f4)})
    posn = posn.set_index("dt").resample("12h").last().reset_index()   # causal: last closed 4h bar
    g = f[["dt", "close", "atr14", "ofi6_res", "fund_z"]].merge(
        xf[["dt", "f_cmpx", "f_ethrel", "btc_dom_z"]], on="dt", how="left").merge(
        iv, on="dt", how="left").merge(posn, on="dt", how="left")
    g = g[g.dt >= start].reset_index(drop=True)
    g["s_flow"] = zs(g.ofi6_res.to_numpy(float), 480)
    g["s_ivol"] = zs(g.iv_mom.to_numpy(float), 120)
    g["s_cmpx"] = g.f_cmpx
    g["s_ethrel"] = -g.f_ethrel
    g["s_btcdom"] = g.btc_dom_z
    g["s_fundz"] = -g.fund_z
    g["s_posn"] = g.posn
    return g

THR = {"flow": 1.0, "ivol": 0.7, "cmpx": 1.0, "ethrel": 1.0,
       "btcdom": 1.0, "fundz": 1.0, "posn": 0.7}

def unit(g, name):
    """One signal's contribution: 0 inside its band, +/-1 outside, scaled by |z|."""
    z = g[f"s_{name}"].to_numpy(float); t = THR[name]
    e = np.where(z > t, 1.0, np.where(z < -t, -1.0, 0.0))
    return np.nan_to_num(e * np.clip(np.abs(z) / t, 1.0, CAP))

def composite(g, names, w=None):
    U = np.column_stack([unit(g, n) for n in names])
    if w is None: w = np.ones(len(names))
    w = np.asarray(w, float); w = w / w.sum()
    return U @ w

def book(g, net, stp=3.0, rr=2.0, dead=0.0, scale=1.0):
    a = g.atr14.to_numpy(float)
    e = np.where(np.abs(net) > dead, net * scale, 0.0)
    return dict(entry=np.nan_to_num(e), stop=stp * a, tp=stp * rr * a,
                exit=np.zeros(len(g)))

def show(tag, g, net, start, risk, dead=0.0, scale=1.0, hold=7, boot=False):
    a = book(g, net, dead=dead, scale=scale)
    kw = dict(risk=risk, max_lev=10.0, max_bars_h=hold * 24)
    A = backtest(g, a, "12h", start=start, end=OOS_END, **kw)
    I = backtest(g, a, "12h", start=start, end=IS_END, **kw)
    O = backtest(g, a, "12h", start=IS_END, end=OOS_END, **kw)
    line = (f"{tag:>34} | {A['cagr']*100:7.1f}%{A['max_dd']*100:7.1f}%{A['profit_factor']:6.2f}"
            f"{A['trades']:6d}{A['sharpe']:6.2f}{A['calmar']:6.2f} | "
            f"{I['cagr']*100:6.1f}%{O['cagr']*100:7.1f}%{O['profit_factor']:6.2f}")
    if boot:
        r = pd.Series(A["equity"], index=pd.to_datetime(A["dt"])).resample("1D").last(
            ).dropna().pct_change().fillna(0).to_numpy()
        b = bootstrap_dd(r, n=2000)
        line += f" | med {b['dd_median']*100:5.1f}% P>20% {b['p_dd_worse_than_20']*100:3.0f}%"
    print(line)
    return A

HDR = (f"{'strategy':>34} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'Shp':>6}{'Clm':>6}"
       f" | {'IS':>6}{'OOS':>7}{'OOSPF':>6}")

if __name__ == "__main__":
    ALL = ["flow", "ivol", "cmpx", "ethrel", "btcdom", "fundz", "posn"]
    FULL = ["flow", "cmpx", "ethrel", "btcdom", "fundz", "posn"]     # no IV before 2023-06

    for start, names, lab in ((BV_START, ALL, "BVOL window 2023-06 -> 2026-08, 7 signals"),
                              (FULL_START, FULL, "FULL window 2021-03 -> 2026-08, 6 signals")):
        g = grid(start)
        print(f"\n===== {lab}   {len(g)} decision bars")
        print("--- each signal on its own, one account, same rules")
        print(HDR)
        for n in names:
            show(f"{n} alone", g, unit(g, n), start, 0.02)
        print("--- the net position: all signals summed into one")
        net = composite(g, names)
        for risk in (0.02, 0.05, 0.08):
            show(f"net, risk {risk*100:.0f}%", g, net, start, risk, boot=(risk == 0.05))
        print("--- net, with a dead band so weak agreement is not traded")
        for dead in (0.15, 0.30, 0.45):
            show(f"net, dead band {dead}", g, net, start, 0.05, dead=dead, boot=True)
