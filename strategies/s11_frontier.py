"""
S11 - Portfolio frontier with honest leverage and IS-derived weights.

Weights are inverse-volatility (risk parity), estimated on the IN-SAMPLE window
ONLY and then applied unchanged out-of-sample - so the allocation is not fitted
to the OOS data. Each sleeve is re-simulated at its true size at every knob, so
the carry sleeve pays its real USDT borrow cost.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import IS_START, IS_END, OOS_END
from research.robust import bootstrap_dd, summarise
from strategies.s09_portfolio_real import sleeves, combine

def run(knobs=(1, 2, 3, 4, 6, 8), label=""):
    # ---- IS-only weights ---------------------------------------------------
    sl_is = sleeves(1, IS_START, IS_END)
    cols = [c for c in sl_is if not c.startswith("_")]
    vol = {c: sl_is[c].std() for c in cols}
    inv = {c: (1.0 / v if v > 0 else 0.0) for c, v in vol.items()}
    tot = sum(inv.values())
    rp = {c: inv[c] / tot for c in cols}
    print("IS sleeve vol (ann.) and risk-parity weight:")
    for c in cols:
        print(f"   {c:<6} vol {vol[c]*np.sqrt(365.25)*100:5.1f}%   weight {rp[c]*100:5.1f}%")
    eq = {c: 1.0 for c in cols}

    for wname, w in (("equal", eq), ("riskparity(IS)", rp)):
        print(f"\n--- weights: {wname} ---")
        print(f"{'knob':>5} | {'IS  CAGR':>9}{'DD':>8}{'Shp':>6} | {'OOS CAGR':>9}{'DD':>8}{'Shp':>6}"
              f" | {'ALL CAGR':>9}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}{'N':>6}")
        for k in knobs:
            r = {}
            for lab, s, e in (("IS", IS_START, IS_END), ("OOS", IS_END, OOS_END), ("ALL", IS_START, OOS_END)):
                r[lab] = combine(sleeves(k, s, e), w)
            a = r["ALL"]
            print(f"{k:>5} | {r['IS']['cagr']*100:8.1f}%{r['IS']['max_dd']*100:7.1f}%{r['IS']['sharpe']:6.2f}"
                  f" | {r['OOS']['cagr']*100:8.1f}%{r['OOS']['max_dd']*100:7.1f}%{r['OOS']['sharpe']:6.2f}"
                  f" | {a['cagr']*100:8.1f}%{a['max_dd']*100:7.1f}%{a['pf']:6.2f}{a['sharpe']:6.2f}"
                  f"{a['calmar']:6.2f}{a['trades']:6d}")
            if wname.startswith("risk") and k in (6, 8):
                rr = pd.Series(a["equity"], index=a["index"]).pct_change().fillna(0)
                b = bootstrap_dd(rr.to_numpy())
                print(f"        bootstrap: median DD {b['dd_median']*100:.1f}%  5th pct {b['dd_p05']*100:.1f}%  "
                      f"P(DD worse than -20%) = {b['p_dd_worse_than_20']*100:.0f}%  "
                      f"median CAGR {b['cagr_median']*100:.0f}%")

if __name__ == "__main__":
    run()
