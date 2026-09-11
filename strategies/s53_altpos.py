"""
S53 - Is the rest of the market crowded the same way?

The book already reads BTC's own positioning - how long top traders and retail
accounts are on BTCUSDT. What it has never read is whether the REST of the perp
market is positioned the same way. Eight major alts (ETH, SOL, XRP, BNB, DOGE,
ADA, LINK, AVAX) publish the identical metrics, and the people levered long
DOGE are not the same people levered long BTC.

Five aggregate reads, each z-scored and used exactly like every other signal:

  alt_tt      mean top-trader position ratio across the eight
  alt_retail  mean retail account long/short ratio
  alt_oi      45-bar change in aggregate alt open-interest value
  alt_taker   mean taker buy/sell volume ratio
  alt_vs_btc  alt retail crowding MINUS BTC retail crowding - the part of alt
              positioning that BTC positioning does not already explain

Coverage is 2021-12-01 onward: Binance does not publish alt metrics before
that, so this is measured on 4.7 years rather than 5.5.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import backtest, IS_END, OOS_END
from research.runner import zs
import strategies.s45_single as S
import strategies.s46_net as S46

START = "2021-12-02"

def altpanel():
    a = pd.read_parquet(str(_P.DATA / "altmetrics_1h.parquet"))
    a["dt"] = pd.to_datetime(a.dt, utc=True).astype("datetime64[ns, UTC]")
    num = ["sum_open_interest_value", "sum_toptrader_long_short_ratio",
           "count_toptrader_long_short_ratio", "count_long_short_ratio",
           "sum_taker_long_short_vol_ratio"]
    for c in num:
        if c in a: a[c] = pd.to_numeric(a[c], errors="coerce")
    agg = a.groupby("dt").agg(
        tt=("sum_toptrader_long_short_ratio", "mean"),
        ttc=("count_toptrader_long_short_ratio", "mean"),
        retail=("count_long_short_ratio", "mean"),
        taker=("sum_taker_long_short_vol_ratio", "mean"),
        oi=("sum_open_interest_value", "sum")).reset_index()
    agg = agg.set_index("dt").resample("12h").last().reset_index()

    g = S.grid(S.FULL_START).merge(agg, on="dt", how="left")
    import strategies.s38_orth as s38
    xf = s38.xpanel("12h")
    g = g.merge(xf[["dt", "retail_acct"]], on="dt", how="left")
    g = g[g.dt >= START].reset_index(drop=True)
    for c in ("tt", "ttc", "retail", "taker", "oi"):
        g[c] = g[c].ffill(limit=4)
    W = 120
    g["a_alt_tt"] = zs(g.tt.to_numpy(float), W)
    g["a_alt_retail"] = zs(g.retail.to_numpy(float), W)
    g["a_alt_oi"] = zs(pd.Series(np.log(g.oi.to_numpy(float))).diff(45).to_numpy(), W)
    g["a_alt_taker"] = zs(g.taker.to_numpy(float), W)
    g["a_alt_vs_btc"] = zs(g.retail.to_numpy(float), W) - zs(g.retail_acct.to_numpy(float), W)
    return g

def unit(g, col, thr=1.0):
    z = g[col].to_numpy(float)
    e = np.where(z > thr, 1.0, np.where(z < -thr, -1.0, 0.0))
    return np.nan_to_num(e * np.clip(np.abs(z) / thr, 1.0, S.CAP))

def go(g, v, risk=0.08, start=START, end=OOS_END, hold=21):
    a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(v), stop=3.0 * a, tp=6.0 * a,
               exit=(np.abs(np.nan_to_num(v)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

if __name__ == "__main__":
    g = altpanel()
    print(f"{len(g)} bars  {g.dt.min().date()} -> {g.dt.max().date()}")
    base = S.composite(g, S46.LONG)
    bm = go(g, base)
    br = daily(bm)
    print(f"five-signal book on this window: CAGR {bm['cagr']*100:.1f}%  DD {bm['max_dd']*100:.1f}%"
          f"  PF {bm['profit_factor']:.2f}  N {bm['trades']}  Sharpe {bm['sharpe']:.2f}\n")
    print(f"{'alt signal':>14}{'sgn':>5}{'corr':>7} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>5}{'Shp':>6}"
          f" | {'IS PF':>6}{'OOS PF':>7}{'OOS CAGR':>9}")
    keep = []
    for c in [x for x in g.columns if x.startswith("a_")]:
        best = None
        for sign in (1, -1):
            v = sign * unit(g, c)
            I = go(g, v, risk=0.04, end=IS_END)
            if I["trades"] < 40: continue
            if best is None or I["sharpe"] > best[0]: best = (I["sharpe"], sign, I)
        if best is None:
            print(f"{c[2:]:>14}   too few trades"); continue
        _, sign, I = best
        v = sign * unit(g, c)
        A = go(g, v, risk=0.04); O = go(g, v, risk=0.04, start=IS_END)
        r = daily(A).reindex(br.index).fillna(0.0)
        corr = float(np.corrcoef(r, br)[0, 1])
        print(f"{c[2:]:>14}{sign:>5}{corr:>7.2f} | {A['cagr']*100:7.1f}%{A['max_dd']*100:7.1f}%"
              f"{A['profit_factor']:6.2f}{A['trades']:5d}{A['sharpe']:6.2f} | "
              f"{I['profit_factor']:6.2f}{O['profit_factor']:7.2f}{O['cagr']*100:8.1f}%")
        if I["profit_factor"] > 1.05 and O["profit_factor"] > 1.05 and abs(corr) < 0.40:
            keep.append((c, sign))
    print(f"\nsurvivors: {[(c[2:], s) for c, s in keep]}")
    if keep:
        print(f"\n{'book':>34}{'risk':>6} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'Shp':>6}{'Clm':>6}"
              f" | {'IS':>6}{'OOS':>7}")
        for tag, extra in [("5 signals (control)", [])] + [(f"+ {c[2:]}", [(c, s)]) for c, s in keep] \
                          + ([("+ all survivors", keep)] if len(keep) > 1 else []):
            U = [S.unit(g, n) for n in S46.LONG] + [s * unit(g, c) for c, s in extra]
            v = np.column_stack(U) @ (np.ones(len(U)) / len(U))
            for risk in (0.08,):
                A = go(g, v, risk); I = go(g, v, risk, end=IS_END); O = go(g, v, risk, start=IS_END)
                print(f"{tag:>34}{risk*100:5.0f}% | {A['cagr']*100:7.1f}%{A['max_dd']*100:7.1f}%"
                      f"{A['profit_factor']:6.2f}{A['trades']:6d}{A['sharpe']:6.2f}"
                      f"{A['calmar']:6.2f} | {I['cagr']*100:6.1f}%{O['cagr']*100:7.1f}%")
