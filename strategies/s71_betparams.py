"""
S71 - The three betting parameters nobody has looked at.

Two things have moved the number in this study and both were about HOW the bet
is shaped, not what it predicts: the conviction exponent, and matching the
selection objective to Calmar. Three shape parameters are still set by hand and
have never been examined at all:

  CAP     |net| is clipped at 3.0.  That number was typed once.  It is the sole
          bound on how large a fully-unanimous signal can bet, and at exponent 3
          it is what makes a single trade risk up to 33% of equity.
  EXIT    the flat-exit fires when |net| reaches EXACTLY zero.  A conviction
          that has decayed to 0.05 is still held at whatever size it was opened.
          Exiting on decay rather than on extinction is a different rule.
  THR     each signal contributes nothing until its z-score passes 1.0 (0.7 for
          positioning).  Those were the first numbers tried and were never
          revisited; a dead band on the NET was tested and failed, but the
          per-signal bands never were.

Stage 1 (this file): hold the exponent, stop, target and hold at the current
best and sweep the three by themselves, to find out whether any of them matters
before spending a quarterly grid on it.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

BASE = dict(exp=2.5, stp=2.5, rr=3.0, hold=14)
_C = {}
def ctx():
    if not _C:
        g = S.grid(S.FULL_START)
        _C.update(g=g, a=g.atr14.to_numpy(float))
    return _C

def net(thr_scale=1.0, exp=2.5, cap=3.0):
    g = ctx()["g"]
    U = []
    for n in S46.LONG:
        z = g[f"s_{n}"].to_numpy(float); t = S.THR[n] * thr_scale
        e = np.where(z > t, 1.0, np.where(z < -t, -1.0, 0.0))
        U.append(np.nan_to_num(e * np.clip(np.abs(z) / t, 1.0, S.CAP)))
    v = np.column_stack(U) @ (np.ones(len(U)) / len(U))
    nz = np.abs(v) > 0
    if nz.sum() < 50: return v
    u = np.sign(v) * np.abs(v) ** exp
    u = u * (np.abs(v[nz]).mean() / max(np.abs(u[nz]).mean(), 1e-12))
    return np.sign(u) * np.minimum(np.abs(u), cap)

def run(v, exit_thr, risk, stp, rr, hold, start=S.FULL_START, end=OOS_END):
    a = ctx()["a"]
    arr = dict(entry=np.nan_to_num(v), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(v)) <= exit_thr).astype(float))
    return backtest(ctx()["g"], arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)

def show(tag, m, r):
    b = bootstrap_dd(pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0).to_numpy(), n=1500)
    cal = m["calmar"]
    print(f"{tag:>34} | CAGR {m['cagr']*100:7.1f}%  DD {m['max_dd']*100:6.1f}%  "
          f"PF {m['profit_factor']:5.2f}  N {m['trades']:4d}  Shp {m['sharpe']:5.2f}  "
          f"Clm {cal:5.2f} | med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")
    return cal

if __name__ == "__main__":
    R = 0.08
    print(f"exponent {BASE['exp']}, {BASE['stp']} ATR x {BASE['rr']}R, {BASE['hold']}d hold, "
          f"risk {R*100:.0f}%, full window\n")
    print("--- |net| cap")
    for cap in (2.0, 3.0, 4.0, 6.0):
        show(f"cap {cap}", run(net(cap=cap), 0.0, R, BASE["stp"], BASE["rr"], BASE["hold"]), R)
    print("\n--- flat-exit threshold (exit when |net| <= x)")
    for ex in (0.0, 0.05, 0.10, 0.20, 0.35):
        show(f"exit at |net| <= {ex}", run(net(), ex, R, BASE["stp"], BASE["rr"], BASE["hold"]), R)
    print("\n--- per-signal threshold scale")
    for ts in (0.7, 0.85, 1.0, 1.2, 1.5):
        show(f"threshold x{ts}", run(net(thr_scale=ts), 0.0, R, BASE["stp"], BASE["rr"], BASE["hold"]), R)
