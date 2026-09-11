"""
S76 - Other instruments as SIGNALS for a BTCUSDT-only position.

Back to one instrument: every position is BTCUSDT, one at a time, one account.
But the data pulled for the cross-sectional test does not have to be traded to
be useful.  What the alts know about the alts may say something about BTC.

S53 already tested aggregate alt POSITIONING added to the book and it hurt.
That closed one door, not the corridor: it used a single 8-alt average of the
account ratios, and never touched alt order flow, alt funding, the DISPERSION
between alts, or the most interesting construction of all - BTC's own signal
minus the alt average, which is the part of BTC's flow that the rest of the
market is not doing.

Six candidates, each added to the five-signal net one at a time and judged by
what the BOOK does (the only valid screen for a netted strategy, per S53):

  alt_flow      mean orthogonalised taker-flow z across the alts
  alt_posn      mean positioning composite across the alts
  alt_fund      mean funding z across the alts
  disp_flow     cross-sectional dispersion of alt flow - are they agreeing?
  rel_flow      BTC flow z MINUS mean alt flow z
  rel_posn      BTC positioning MINUS mean alt positioning

Selection on in-sample marginal Calmar only; out-of-sample reported, never used
to choose.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs
import strategies.s45_single as S
import strategies.s46_net as S46
import strategies.s74_multi as M

ALTS = ["ETHUSDT", "SOLUSDT", "ZECUSDT", "XRPUSDT"]
START = "2022-01-01"

_B = {}
def build():
    if _B: return _B
    g = S.grid(S.FULL_START)
    g = g[g.dt >= START].reset_index(drop=True)
    flows, posns, funds = {}, {}, {}
    for a in ALTS:
        p = M.panel(a)
        s = p.set_index("dt")
        flows[a] = s["s_flow"].reindex(g.dt).to_numpy()
        posns[a] = s["s_posn"].reindex(g.dt).to_numpy()
        funds[a] = s["s_fundz"].reindex(g.dt).to_numpy()
    F = np.column_stack([flows[a] for a in ALTS])
    P = np.column_stack([posns[a] for a in ALTS])
    U = np.column_stack([funds[a] for a in ALTS])
    g["a_alt_flow"] = np.nanmean(F, axis=1)
    g["a_alt_posn"] = np.nanmean(P, axis=1)
    g["a_alt_fund"] = np.nanmean(U, axis=1)
    g["a_disp_flow"] = zs(np.nanstd(F, axis=1), 120)
    g["a_rel_flow"] = g.s_flow.to_numpy(float) - np.nanmean(F, axis=1)
    g["a_rel_posn"] = g.s_posn.to_numpy(float) - np.nanmean(P, axis=1)
    _B["g"] = g
    return _B

def unit(g, col, thr=1.0):
    z = g[col].to_numpy(float)
    e = np.where(z > thr, 1.0, np.where(z < -thr, -1.0, 0.0))
    return np.nan_to_num(e * np.clip(np.abs(z) / thr, 1.0, S.CAP))

def run(g, v, start, end, risk=0.08, exp=2.5, stp=2.5, rr=3.0, hold=14):
    nz = np.abs(v) > 0
    if nz.sum() > 50 and exp != 1.0:
        u = np.sign(v) * np.abs(v) ** exp
        v = np.sign(u) * np.minimum(np.abs(u) * (np.abs(v[nz]).mean() /
                                    max(np.abs(u[nz]).mean(), 1e-12)), 3.0)
    a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(v), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(v)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)

def calmar(m):
    return m["cagr"] / abs(m["max_dd"]) if m["max_dd"] < 0 and m["trades"] > 20 else -9e9

if __name__ == "__main__":
    g = build()["g"]
    U0 = [S.unit(g, n) for n in S46.LONG]
    base = np.column_stack(U0) @ (np.ones(len(U0)) / len(U0))
    bI = run(g, base, START, IS_END); bA = run(g, base, START, OOS_END)
    bO = run(g, base, IS_END, OOS_END)
    print(f"window {START} -> {OOS_END}   (alt panels begin 2022-01)")
    print(f"base book: IS Calmar {calmar(bI):.2f}   ALL CAGR {bA['cagr']*100:.1f}% "
          f"DD {bA['max_dd']*100:.1f}% PF {bA['profit_factor']:.2f} Shp {bA['sharpe']:.2f} "
          f"Clm {calmar(bA):.2f}   OOS Clm {calmar(bO):.2f}\n")
    print(f"{'candidate':>14}{'sgn':>5}{'dIS Clm':>9} | {'ALL CAGR':>9}{'DD':>7}{'PF':>6}{'N':>6}"
          f"{'Shp':>6}{'Clm':>6} | {'OOS CAGR':>9}{'PF':>6}{'Clm':>6}")
    rows = []
    for c in [x for x in g.columns if x.startswith("a_")]:
        for sign in (1, -1):
            u = sign * unit(g, c)
            v = np.column_stack(U0 + [u]) @ (np.ones(len(U0) + 1) / (len(U0) + 1))
            I = run(g, v, START, IS_END)
            if I["trades"] < 60: continue
            rows.append((calmar(I) - calmar(bI), c, sign, v))
    rows.sort(key=lambda x: -x[0])
    for d, c, sign, v in rows[:8]:
        A = run(g, v, START, OOS_END); O = run(g, v, IS_END, OOS_END)
        print(f"{c[2:]:>14}{sign:>5}{d:>9.3f} | {A['cagr']*100:8.1f}%{A['max_dd']*100:6.1f}%"
              f"{A['profit_factor']:6.2f}{A['trades']:6d}{A['sharpe']:6.2f}{calmar(A):6.2f} | "
              f"{O['cagr']*100:8.1f}%{O['profit_factor']:6.2f}{calmar(O):6.2f}")
    print(f"{'BASE':>14}{'':>5}{0.0:>9.3f} | {bA['cagr']*100:8.1f}%{bA['max_dd']*100:6.1f}%"
          f"{bA['profit_factor']:6.2f}{bA['trades']:6d}{bA['sharpe']:6.2f}{calmar(bA):6.2f} | "
          f"{bO['cagr']*100:8.1f}%{bO['profit_factor']:6.2f}{calmar(bO):6.2f}")
