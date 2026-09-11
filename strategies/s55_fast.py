"""
S55 - Attacking the bet count directly.

Sharpe = IC x sqrt(bets per year). The book takes ~183 trades a year at 12h
decisions and reaches Sharpe 2.20. Reaching the target needs roughly Sharpe 9,
which at constant IC needs ~16x the bets. That is the one term in the identity
this study has never attacked head-on for the net book: every timeframe test in
the study was run on SINGLE signals, never on the netted combination, and the
combination behaves differently because opposing signals cancel before costs.

The underlying data supports it. Funding updates every 8h, positioning and open
interest every 5 minutes, the coin-margined and alt prices every second. Nothing
about these signals is intrinsically 12-hourly - that was a choice made early
and never revisited.

Rebuilt at 1h, 2h, 4h and 6h decisions with every rolling window rescaled to
cover the same wall-clock span, so the signals mean the same thing at each
frequency and only the decision rate changes.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs
import strategies.s07_smart as s07
import strategies.s38_orth as s38
import strategies.s36_ivmom as s36

START = "2021-03-01"
THR = {"flow": 1.0, "cmpx": 1.0, "btcdom": 1.0, "fundz": 1.0, "posn": 0.7}
CAP = 2.0
NAMES = ["flow", "cmpx", "btcdom", "fundz", "posn"]
_C = {}

def grid(tf):
    """One decision panel at `tf`, windows rescaled to the same wall-clock span."""
    if tf in _C: return _C[tf]
    per_day = int(pd.Timedelta("1D") / pd.Timedelta(tf))
    k = per_day / 2.0                     # 12h grid had 2 bars/day
    fut, f = panel(tf)
    f["dt"] = pd.to_datetime(f.dt, utc=True).astype("datetime64[ns, UTC]")
    # coin-margined price, BTC dominance, funding: resample the hourly sources onto tf
    D = str(_P.DATA)
    def rs(df, col, tcol="dt"):
        df[tcol] = pd.to_datetime(df[tcol], utc=True).astype("datetime64[ns, UTC]")
        return df.set_index(tcol)[col].resample(tf).last()
    cm = rs(pd.read_parquet(f"{D}/cm_1h.parquet"), "close").rename("cm_px")
    b = pd.read_parquet(f"{D}/breadth.parquet")
    b.index = pd.to_datetime(b.index, utc=True) if b.index.tz is None else b.index.tz_convert("UTC")
    dom = b["btc_dom"].resample(tf).last().rename("btc_dom")
    f = f.merge(cm.reset_index(), on="dt", how="left").merge(
        dom.reset_index().rename(columns={"index": "dt"}), on="dt", how="left")
    for c in ("cm_px", "btc_dom"):
        f[c] = f[c].ffill(limit=per_day)
    _, f4 = panel("4h")
    f4["dt"] = pd.to_datetime(f4.dt, utc=True).astype("datetime64[ns, UTC]")
    po = pd.DataFrame({"dt": f4.dt, "posn": s07.composite(f4)}).set_index("dt")
    po = (po.resample(tf).last().ffill(limit=per_day) if per_day > 6
          else po.resample(tf).last()).reset_index()
    f = f.merge(po, on="dt", how="left")
    f = f[f.dt >= START].reset_index(drop=True)
    w = lambda n: max(int(round(n * k)), 8)
    f["s_flow"] = zs(f.ofi6_res.to_numpy(float), w(480))
    f["s_cmpx"] = zs(pd.Series(np.log(f.cm_px / f.close)).diff(w(6)).to_numpy(), w(120))
    f["s_btcdom"] = zs(f.btc_dom.to_numpy(float), w(120))
    f["s_fundz"] = -zs(f.fund.to_numpy(float), w(120))
    f["s_posn"] = f.posn
    _C[tf] = f
    return f

def unit(f, n):
    z = f[f"s_{n}"].to_numpy(float); t = THR[n]
    e = np.where(z > t, 1.0, np.where(z < -t, -1.0, 0.0))
    return np.nan_to_num(e * np.clip(np.abs(z) / t, 1.0, CAP))

def net(f, names=NAMES):
    U = [unit(f, n) for n in names]
    return np.column_stack(U) @ (np.ones(len(U)) / len(U))

def run(tf, risk, hold_d=21, stp=3.0, rr=2.0, start=START, end=OOS_END, flat=True):
    f = grid(tf); v = net(f); a = f.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(v), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(v)) <= 0.0).astype(float) if flat else np.zeros(len(f)))
    return backtest(f, arr, tf, start=start, end=end, risk=risk, max_lev=10.0,
                    max_bars_h=hold_d * 24)

if __name__ == "__main__":
    print(f"{'tf':>5}{'risk':>6} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'N/yr':>6}{'Shp':>6}{'Clm':>6}"
          f"{'Exp':>6} | {'IS':>7}{'OOS':>8}{'OOSPF':>6} | {'medDD':>7}{'P>20%':>6}")
    for tf in ("12h", "6h", "4h", "2h", "1h"):
        for risk in (0.04, 0.08):
            try:
                A = run(tf, risk); I = run(tf, risk, end=IS_END); O = run(tf, risk, start=IS_END)
            except Exception as e:
                print(f"{tf:>5}{risk*100:5.0f}% | error {e}"); continue
            r = pd.Series(A["equity"], index=pd.to_datetime(A["dt"])).resample("1D").last(
                ).dropna().pct_change().fillna(0).to_numpy()
            b = bootstrap_dd(r, n=1500)
            yrs = 5.5
            print(f"{tf:>5}{risk*100:5.0f}% | {A['cagr']*100:7.1f}%{A['max_dd']*100:7.1f}%"
                  f"{A['profit_factor']:6.2f}{A['trades']:6d}{A['trades']/yrs:6.0f}{A['sharpe']:6.2f}"
                  f"{A['calmar']:6.2f}{A['exposure']*100:5.0f}% | {I['cagr']*100:6.1f}%"
                  f"{O['cagr']*100:7.1f}%{O['profit_factor']:6.2f} | {b['dd_median']*100:6.1f}%"
                  f"{b['p_dd_worse_than_20']*100:5.0f}%")
