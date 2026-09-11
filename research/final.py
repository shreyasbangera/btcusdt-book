"""
Final validation of the strategies that survived the screen.

For each finalist:
  * IS / OOS / full-period metrics
  * cost stress at 1x, 1.5x and 2x the baseline 16 bps round-turn
  * stationary block-bootstrap distribution of max drawdown
  * yearly returns
Equity curves are saved for the report.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd, json
from research.harness import panel, backtest, IS_START, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s07_smart as s07
import strategies.s03_ofi_swing as s03
import strategies.s04_advol as s04
import strategies.s01_prfc as s01
import strategies.s05_carry as s05
from strategies.s09_portfolio_real import sleeves, combine

OUT = str(_P.RESULTS)

def dir_strategy(name, f, arr_fn, tf, risk, since=None, **kw):
    res = {}
    for lab, s, e in (("IS", since or IS_START, IS_END), ("OOS", IS_END, OOS_END),
                      ("ALL", since or IS_START, OOS_END)):
        res[lab] = backtest(f, arr_fn(), tf, start=s, end=e, risk=risk, **kw)
    stress = {}
    for mult in (1.0, 1.5, 2.0):
        m = backtest(f, arr_fn(), tf, start=since or IS_START, end=OOS_END,
                     risk=risk, fee=5.0*mult, slip=3.0*mult, **kw)
        stress[f"{mult}x"] = dict(cagr=m["cagr"], pf=m["profit_factor"], dd=m["max_dd"])
    eq = pd.Series(res["ALL"]["equity"], index=res["ALL"]["dt"])
    dly = eq.resample("1D").last().dropna().pct_change().fillna(0)
    boot = bootstrap_dd(dly.to_numpy(), n=1500)
    return res, stress, boot, eq

def row(lab, m):
    return (f"    {lab:<5} CAGR {m['cagr']*100:8.1f}%  DD {m['max_dd']*100:6.1f}%  PF {m['profit_factor']:5.2f}  "
            f"N {m['trades']:5d}  WR {m['win_rate']*100:4.1f}%  Sharpe {m['sharpe']:5.2f}  Calmar {m['calmar']:6.2f}")

def show(name, res, stress, boot, extra=""):
    print(f"\n### {name} {extra}")
    for lab in ("IS", "OOS", "ALL"):
        print(row(lab, res[lab]))
    y = res["ALL"]["yearly"]
    print("      yearly: " + " ".join(f"{k}:{v*100:+.0f}%" for k, v in y.items()))
    print("      cost stress (CAGR/PF/DD): " + "  ".join(
        f"{k}: {v['cagr']*100:.1f}%/{v['pf']:.2f}/{v['dd']*100:.1f}%" for k, v in stress.items()))
    print(f"      bootstrap DD: median {boot['dd_median']*100:.1f}%  5th pct {boot['dd_p05']*100:.1f}%  "
          f"P(DD<-20%) {boot['p_dd_worse_than_20']*100:.0f}%")

if __name__ == "__main__":
    curves = {}
    fut4, f4 = panel("4h")
    f4m = f4[f4.dt >= "2021-01-03"].reset_index(drop=True)

    # --- S7 SMRD at 1% and at the risk that puts DD near the 20% cap --------
    comp = s07.composite(f4m)
    for risk in (0.01, 0.025):
        res, st, bt, eq = dir_strategy("SMRD", f4m,
            lambda: s07.arrays(f4m, comp, thr=0.7, atr_stop=3.5, rr=2.5), "4h",
            risk=risk, since="2021-01-03", max_lev=10.0, max_bars_h=10*24)
        show(f"S7 SMRD (risk {risk*100:.1f}%/trade)", res, st, bt)
        curves[f"SMRD_r{risk}"] = eq

    # --- S4 AVT -------------------------------------------------------------
    for risk in (0.01, 0.025):
        res, st, bt, eq = dir_strategy("AVT", f4,
            lambda: s04.arrays(f4, dc_n=40, adx_min=20, er_min=0.30, vol_adapt=False), "4h",
            risk=risk, max_lev=10.0, trail_after_r=1.0)
        show(f"S4 AVT (risk {risk*100:.1f}%/trade)", res, st, bt)
        curves[f"AVT_r{risk}"] = eq

    # --- S3 OFS -------------------------------------------------------------
    res, st, bt, eq = dir_strategy("OFS", f4,
        lambda: s03.arrays(f4, thr=0.75, atr_stop=3.5, rr=2.5, trend_filter=True,
                           flow="ofi24_resz"), "4h",
        risk=0.02, max_lev=10.0, max_bars_h=10*24)
    show("S3 OFS (risk 2.0%/trade)", res, st, bt)
    curves["OFS_r0.02"] = eq

    # --- S9 portfolio at several knobs -------------------------------------
    print("\n### S9/S11 Multi-strategy portfolio (equal weight, honest leverage)")
    print(f"{'knob':>5} | {'IS CAGR':>9}{'DD':>8} | {'OOS CAGR':>9}{'DD':>8} | {'ALL CAGR':>9}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>6}{'N':>6}")
    for k in (4, 5, 6):
        r = {lab: combine(sleeves(k, s, e))
             for lab, s, e in (("IS", IS_START, IS_END), ("OOS", IS_END, OOS_END), ("ALL", IS_START, OOS_END))}
        a = r["ALL"]
        print(f"{k:>5} | {r['IS']['cagr']*100:8.1f}%{r['IS']['max_dd']*100:7.1f}% | "
              f"{r['OOS']['cagr']*100:8.1f}%{r['OOS']['max_dd']*100:7.1f}% | "
              f"{a['cagr']*100:8.1f}%{a['max_dd']*100:7.1f}%{a['pf']:6.2f}{a['sharpe']:6.2f}{a['calmar']:6.2f}{a['trades']:6d}")
        eqp = pd.Series(a["equity"], index=a["index"])
        dly = eqp.pct_change().fillna(0)
        b = bootstrap_dd(dly.to_numpy(), n=1500)
        print(f"        yearly: " + " ".join(f"{y}:{v*100:+.0f}%" for y, v in a["yearly"].items()))
        print(f"        bootstrap DD median {b['dd_median']*100:.1f}%  5th pct {b['dd_p05']*100:.1f}%  "
              f"P(DD<-20%) {b['p_dd_worse_than_20']*100:.0f}%")
        curves[f"PORT_k{k}"] = eqp

    pd.DataFrame({k: v for k, v in curves.items()}).to_parquet(f"{OUT}/curves.parquet")
    print("\nsaved curves ->", f"{OUT}/curves.parquet")
