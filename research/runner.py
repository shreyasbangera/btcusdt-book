"""Compact sweep runner: many parameter variants, one line each."""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd, json, os
from research.harness import backtest, IS_START, IS_END, OOS_END, qualifies

STORE = str(_P.RESULTS / "attempts.json")

def line(tag, m):
    return (f"{tag:<38} CAGR{m['cagr']*100:8.1f}% DD{m['max_dd']*100:6.1f}% "
            f"PF{m['profit_factor']:5.2f} N{m['trades']:5d} WR{m['win_rate']*100:4.1f}% "
            f"Shp{m['sharpe']:5.2f} Clm{m['calmar']:6.2f}")

def evaluate(name, sig_df, arrays, tf, verbose=True, since=None, **kw):
    """`since` moves the start of the IS and ALL windows (e.g. for signals whose
    source data begins later than 2020-01-01)."""
    s0 = since or IS_START
    r = {}
    for lab, s, e in (("IS", s0, IS_END), ("OOS", IS_END, OOS_END), ("ALL", s0, OOS_END)):
        r[lab] = backtest(sig_df, arrays, tf, start=s, end=e, **kw)
    if verbose:
        for lab in ("IS", "OOS", "ALL"):
            print("  " + line(f"{name} [{lab}]", r[lab]))
    return r

def save(name, desc, r, params):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    db = json.load(open(STORE)) if os.path.exists(STORE) else []
    rec = dict(name=name, desc=desc, params=params)
    for lab in ("IS", "OOS", "ALL"):
        m = r[lab]
        rec[lab] = {k: (None if isinstance(v, float) and not np.isfinite(v) else v)
                    for k, v in m.items()
                    if k in ("cagr", "max_dd", "profit_factor", "trades", "win_rate",
                             "sharpe", "calmar", "exposure", "total_return")}
        rec[lab]["yearly"] = {str(k): v for k, v in m["yearly"].items()}
    rec["qualifies_ALL"] = bool(qualifies(r["ALL"]))
    db = [d for d in db if d["name"] != name] + [rec]
    json.dump(db, open(STORE, "w"), indent=1)
    return rec

def zs(x, n):
    s = pd.Series(np.asarray(x, float))
    return ((s - s.rolling(n).mean()) / (s.rolling(n).std() + 1e-12)).to_numpy()
