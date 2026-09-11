"""
The registry of every headline strategy this study has produced.

Each version is kept runnable, not just described.  `python strategies/registry.py`
re-measures all of them from the same data and prints the ranked table, so no
number in STRATEGIES.md is taken on trust and an earlier book is never lost
because a later one replaced it in the log.

Every version is quoted twice: at a common 8% risk so the books are comparable to
each other, and at the risk that puts realised max drawdown on the brief's 20%
gate, found by bisection, which is the only size the 300% target can be judged at.

Drawdown convention: every version is marked DAILY.  The quarterly books are
assembled from per-quarter segments and have no continuous 15-minute equity
curve, so daily marks are the only measure all six share.  It is mildly
optimistic - V1 measured on its own 15-minute curve draws down 14.9% where the
daily marks say 12.7% - so read every drawdown here as "on daily closes" and
add roughly two points for the intraday path.

Windows differ and that is not cosmetic.  V1 needs no selection lookback so it
starts 2021-03; the quarterly books spend their first 12 or 24 months warming up
the selection, so V2 cannot start before 2023-03 and misses the bear market
entirely.  Comparing V2 to V3 on return alone is comparing a 3.5-year bull sample
to a 4.5-year one that contains 2022.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.robust import bootstrap_dd

# ----------------------------------------------------------------- versions

def v1(risk):
    """S46 - five signals, equal weight, one fixed configuration, no selection."""
    from strategies.s46_net import run, LONG
    import strategies.s69_calsel as C
    m = run(LONG, "2021-03-01", risk=risk)
    return C.daily(m), m["trades_df"]["pnl"].to_numpy(float)

def _replay(plan, sim, risk):
    import strategies.s69_calsel as C
    segs, pnl = [], []
    for s, e, cfg in plan:
        m = sim(cfg, s, e, risk); segs.append(C.daily(m))
        td = m["trades_df"]
        if td is not None and len(td): pnl.append(td["pnl"].to_numpy(float))
    return pd.concat(segs), (np.concatenate(pnl) if pnl else np.array([]))

def v2(risk):
    """S69 - quarterly Calmar-selected from 40 configs, 24-month lookback."""
    from research.planscache import cached_plan
    from strategies.s69_calsel import sim
    return _replay(cached_plan(24), sim, risk)

def v3(risk):
    """S77 - the same, 12-month lookback, so the 2022 bear market is traded."""
    from research.planscache import cached_plan
    from strategies.s69_calsel import sim
    return _replay(cached_plan(12), sim, risk)

def v4(risk):
    """S85 - trend gate added to the grid, chosen causally each quarter."""
    from strategies.s85_gategrid import plan, sim
    return _replay(plan(12), sim, risk)

def v5(risk):
    """S86 - top 5 configurations by trailing Calmar, held together at risk/5."""
    from strategies.s86_topk import rankings, blend
    return blend(rankings(), 5, risk)

def v6(risk):
    """S87 - gate menu widened to four spans, top 5 held together."""
    from strategies.s87_combined import rankings, blend
    return blend(rankings(), 5, risk)

def v7(risk):
    """S87 - the same, top 3.  Best Calmar measured in the study."""
    from strategies.s87_combined import rankings, blend
    return blend(rankings(), 3, risk)

def v8(risk):
    """S91 - gate FUNDING's short side rather than the whole composite, chosen
    causally against both alternatives each quarter.  Top 3."""
    from strategies.s91_fundgate import rankings, blend
    return blend(rankings(), 3, risk)

VERSIONS = [
    ("V1  S46  fixed config, 5 signals",        v1, "2021-03 -> 2026-08 (5.5y, incl. bear)"),
    ("V2  S69  quarterly Calmar, 24m lookback", v2, "2023-03 -> 2026-08 (3.5y, NO bear)"),
    ("V3  S77  quarterly Calmar, 12m lookback", v3, "2022-03 -> 2026-08 (4.5y, incl. bear)"),
    ("V4  S85  + trend gate in the grid",       v4, "2022-03 -> 2026-08 (4.5y, incl. bear)"),
    ("V5  S86  + top-5 blend",                  v5, "2022-03 -> 2026-08 (4.5y, incl. bear)"),
    ("V6  S87  + wide gate menu, top-5",        v6, "2022-03 -> 2026-08 (4.5y, incl. bear)"),
    ("V7  S87  + wide gate menu, top-3",        v7, "2022-03 -> 2026-08 (4.5y, incl. bear)"),
    ("V8  S91  gate funding only, top-3",       v8, "2022-03 -> 2026-08 (4.5y, incl. bear)"),
]

# ----------------------------------------------------------------- measuring

def measure(r, P):
    e = np.cumprod(1 + r.to_numpy()); yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((e / np.maximum.accumulate(e) - 1).min())
    cagr = e[-1] ** (1 / yrs) - 1
    pf = P[P > 0].sum() / max(-P[P < 0].sum(), 1e-9) if len(P) else float("nan")
    b = bootstrap_dd(r.to_numpy(), n=2000)
    ys, es, pv = {}, pd.Series(e, index=r.index), 1.0
    for y, g in es.groupby(es.index.year):
        ys[int(y)] = float(g.iloc[-1] / pv - 1); pv = g.iloc[-1]
    return dict(cagr=cagr, dd=dd, pf=pf, n=len(P), yearly=ys,
                sharpe=float(r.mean() / r.std() * np.sqrt(365.25)),
                calmar=cagr / abs(dd), p20=b["p_dd_worse_than_20"], years=yrs)


def at_gate(fn, lo=0.04, hi=0.30, tol=0.004, iters=7):
    """Bisect for the risk whose realised max drawdown sits on -20%."""
    best = None
    for _ in range(iters):
        mid = (lo + hi) / 2
        m = measure(*fn(mid)); m["risk"] = mid
        if best is None or abs(abs(m["dd"]) - 0.20) < abs(abs(best["dd"]) - 0.20):
            best = m
        if abs(abs(m["dd"]) - 0.20) < tol:
            break
        if abs(m["dd"]) > 0.20: hi = mid
        else:                   lo = mid
    return best


HDR = (f"{'strategy':<38}{'risk':>6}{'CAGR':>9}{'MaxDD':>8}{'PF':>6}{'N':>7}"
       f"{'Shp':>6}{'Clm':>6}{'P>20%':>7}  window")

if __name__ == "__main__":
    only = sys.argv[1:] or None
    print("AT A COMMON 8% RISK\n"); print(HDR)
    rows = []
    for tag, fn, win in VERSIONS:
        if only and tag.split()[0] not in only: continue
        m = measure(*fn(0.08))
        print(f"{tag:<38}{'8%':>6}{m['cagr']*100:8.1f}%{m['dd']*100:7.1f}%{m['pf']:6.2f}"
              f"{m['n']:7d}{m['sharpe']:6.2f}{m['calmar']:6.2f}{m['p20']*100:6.0f}%  {win}", flush=True)
    print(f"\nAT THE RISK THAT PUTS REALISED DRAWDOWN ON THE 20% GATE\n"); print(HDR)
    for tag, fn, win in VERSIONS:
        if only and tag.split()[0] not in only: continue
        m = at_gate(fn); rows.append((tag, m, win))
        print(f"{tag:<38}{m['risk']*100:5.1f}%{m['cagr']*100:8.1f}%{m['dd']*100:7.1f}%{m['pf']:6.2f}"
              f"{m['n']:7d}{m['sharpe']:6.2f}{m['calmar']:6.2f}{m['p20']*100:6.0f}%  {win}", flush=True)
        print("      yearly  " + "  ".join(f"{y}:{x*100:+.0f}%" for y, x in m["yearly"].items()),
              flush=True)
    print("\nRANKED BY CAGR AT THE 20% GATE\n")
    for i, (tag, m, _) in enumerate(sorted(rows, key=lambda x: -x[1]["cagr"]), 1):
        gates = []
        gates.append("N>=100 " + ("PASS" if m["n"] >= 100 else "FAIL"))
        gates.append("PF>1.10 " + ("PASS" if m["pf"] > 1.10 else "FAIL"))
        gates.append("DD<20% " + ("PASS" if abs(m["dd"]) < 0.205 else "FAIL"))
        gates.append("CAGR>300% " + ("PASS" if m["cagr"] > 3.0 else "FAIL"))
        print(f"  {i}. {tag:<38}{m['cagr']*100:7.1f}%   " + " | ".join(gates))
    print("\ndone: registry")
