"""
S75 - The cross-section, with everything the single-instrument book learned.

S74 built the identical book on five instruments and found the cross-section
does help - Sharpe 2.14 -> 2.56 - but only after dropping SOLUSDT, whose book
runs at Sharpe 0.35 and drags every subset it appears in.  Choosing that subset
by looking at the full sample is exactly the overfitting this study keeps
catching itself doing, so here the instruments are selected the same way
everything else is: quarterly, on trailing data, and never with sight of the
period being traded.

Each quarter, on the trailing 24 months only:
    per instrument, pick the conviction curve and exits by trailing CALMAR
                    (the S69 rule, which beat Sharpe-ranking by half the risk)
    then keep the instruments whose trailing Calmar clears a floor
    trade the survivors equal-weighted, risk split across them

Controls: all five always on (no selection), and BTCUSDT alone under the
identical rule, which is the number to beat.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from research.robust import bootstrap_dd
import strategies.s74_multi as M

LOOKBACK, RESELECT = 24, 3
GRID = [(p, stp, rr, hold) for p in (1.0, 1.5, 2.0, 2.5, 3.0)
        for stp in (2.5, 3.0) for rr in (2.0, 3.0) for hold in (14, 21)]
START = "2022-01-01"

def sim(sym, cfg, start, end, risk):
    p, stp, rr, hold = cfg
    return M.book(sym, risk, exp=p, stp=stp, rr=rr, hold=hold, start=start, end=end)

def calmar_of(m):
    if m["trades"] < 10 or m["max_dd"] >= 0: return -9e9
    return m["cagr"] / abs(m["max_dd"])

def plan(min_calmar=0.0, verbose=False):
    """Forward-generated: each quarter's configs and instrument set come only
    from the 24 months before it."""
    t0 = pd.Timestamp(START, tz="UTC")
    t = t0 + pd.DateOffset(months=LOOKBACK); end = pd.Timestamp(OOS_END, tz="UTC")
    out = []
    while t < end:
        te = min(t + pd.DateOffset(months=RESELECT), end)
        tr0 = t - pd.DateOffset(months=LOOKBACK)
        chosen = {}
        for sym in M.SYMS:
            best = None
            for cfg in GRID:
                m = sim(sym, cfg, str(tr0.date()), str(t.date()), 0.08)
                sc = calmar_of(m)
                if best is None or sc > best[0]: best = (sc, cfg)
            if best and best[0] > min_calmar:
                chosen[sym] = best[1]
        if not chosen: chosen = {"BTCUSDT": (1.0, 3.0, 2.0, 21)}
        out.append((str(t.date()), str(te.date()), chosen))
        if verbose:
            print(f"    {str(t.date())[:7]}  " +
                  "  ".join(f"{s.replace('USDT','')}:exp{c[0]}" for s, c in chosen.items()),
                  flush=True)
        t = te
    return out

def replay(p, size=1.0, only=None):
    segs = []
    for s, e, chosen in p:
        use = {k: v for k, v in chosen.items() if only is None or k in only}
        if not use: continue
        n = len(use)
        rs = []
        for sym, cfg in use.items():
            m = sim(sym, cfg, s, e, 0.08 * size)
            rs.append(M.daily(m))
        df = pd.DataFrame({i: r for i, r in enumerate(rs)}).fillna(0.0)
        segs.append(df.mean(axis=1))
    return pd.concat(segs)

def stats(r, tag):
    e = np.cumprod(1 + r.to_numpy()); yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((e / np.maximum.accumulate(e) - 1).min()); cagr = e[-1] ** (1/yrs) - 1
    b = bootstrap_dd(r.to_numpy(), n=2500)
    ys = {}; es = pd.Series(e, index=r.index); pv = 1.0
    for y, g in es.groupby(es.index.year): ys[int(y)] = float(g.iloc[-1]/pv - 1); pv = g.iloc[-1]
    print(f"{tag:>34} | CAGR {cagr*100:7.1f}%  DD {dd*100:6.1f}%  "
          f"Shp {r.mean()/r.std()*np.sqrt(365.25):5.2f}  Clm {cagr/abs(dd):5.2f}"
          f" | med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}%")
    print("        yearly " + " ".join(f"{y}:{x*100:+.0f}%" for y, x in ys.items()))

if __name__ == "__main__":
    print(f"quarterly selection, {LOOKBACK}m lookback, Calmar-ranked, window {START} ->\n")
    pf = plan(min_calmar=0.5, verbose=True)
    pa = plan(min_calmar=-9e8)
    print()
    for sz in (1.0, 1.5, 2.0, 2.5):
        stats(replay(pf, sz), f"selected instruments x{sz}")
    print()
    for sz in (1.0, 1.5, 2.0):
        stats(replay(pa, sz), f"all five always x{sz}")
    print()
    for sz in (1.0, 1.25, 1.5):
        stats(replay(pa, sz, only={"BTCUSDT"}), f"BTC alone x{sz}")
