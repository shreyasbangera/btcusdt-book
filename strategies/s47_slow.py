"""
S47 - Frequency separation: the same reads at a different horizon.

The ceiling is s / sqrt(rho-bar), and rho-bar is stuck at 0.10 because every
signal in the book occupies the same band: three-day lookbacks, 12h bars,
seven-to-twenty-one day holds. Two signals sampling the same frequency of the
same price cannot be independent for long.

Signals at a genuinely different frequency can be. A 45-day lookback held for
60 days is reading a different thing about the same market than a 3-day
lookback held for a week - not a better thing, a different one - and the
correlation between them should be mechanically low without any of them being
any good.

Slow versions of every input in the book, plus two that only make sense slow:

  slow_flow    45-day mean of orthogonalised taker imbalance
  slow_cmpx    45-day change in the implied USDT/USD rate
  slow_dom     45-day change in BTC's share of turnover
  slow_posn    45-day mean of the positioning composite
  carry        funding accumulated over 30 days - what it has cost to be long
  slow_oi      45-day change in open interest
  slow_trend   90-day price momentum, the plainest slow signal there is

Held 60 days, stopped at 4 ATR, targeted at 2R. If frequency separation works,
these should correlate near zero with the fast net regardless of how well or
badly they trade on their own.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.runner import zs
import strategies.s45_single as S45
import strategies.s38_orth as s38
import strategies.s07_smart as s07

START = S45.FULL_START
BD = 2                      # 12h bars per day

def slowpanel():
    g = S45.grid(START)
    xf = s38.xpanel("12h")
    g = g.merge(xf[["dt", "oi", "fund"]], on="dt", how="left")
    n = len(g)
    def zl(x, w): return zs(np.asarray(x, float), w)
    g["v_slow_flow"] = zl(pd.Series(g.ofi6_res.to_numpy(float)).rolling(45 * BD).mean(), 180 * BD)
    g["v_slow_cmpx"] = zl(pd.Series(g.s_cmpx.to_numpy(float)).rolling(45 * BD).mean(), 180 * BD)
    g["v_slow_dom"]  = zl(pd.Series(g.s_btcdom.to_numpy(float)).rolling(45 * BD).mean(), 180 * BD)
    g["v_slow_posn"] = zl(pd.Series(g.s_posn.to_numpy(float)).rolling(45 * BD).mean(), 180 * BD)
    g["v_carry"]     = -zl(pd.Series(g.fund.to_numpy(float)).rolling(30 * BD).sum(), 180 * BD)
    g["v_slow_oi"]   = zl(pd.Series(np.log(g.oi.to_numpy(float))).diff(45 * BD), 180 * BD)
    g["v_slow_trend"]= zl(pd.Series(np.log(g.close.to_numpy(float))).diff(90 * BD), 180 * BD)
    return g

def unit(g, col, thr=1.0, cap=2.0):
    z = g[col].to_numpy(float)
    e = np.where(z > thr, 1.0, np.where(z < -thr, -1.0, 0.0))
    return np.nan_to_num(e * np.clip(np.abs(z) / thr, 1.0, cap))

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

if __name__ == "__main__":
    g = slowpanel()
    cols = [c for c in g.columns if c.startswith("v_")]
    fastnet = S45.composite(g, ["flow", "cmpx", "btcdom", "fundz", "posn"])
    fa = S45.book(g, fastnet, stp=3.0, rr=2.0)
    fm = backtest(g, fa, "12h", start=START, end=OOS_END, risk=0.08, max_lev=10.0,
                  max_bars_h=21 * 24)
    fr = daily(fm)
    print(f"fast net (reference): CAGR {fm['cagr']*100:.1f}%  DD {fm['max_dd']*100:.1f}%  "
          f"PF {fm['profit_factor']:.2f}  Sharpe {fm['sharpe']:.2f}\n")
    print(f"{'slow signal':>16}{'sgn':>5}{'corr':>7} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>5}{'Shp':>6}"
          f" | {'IS CAGR':>8}{'PF':>6} | {'OOS CAGR':>9}{'PF':>6}")
    keep = {}
    for c in cols:
        best = None
        for sign in (1, -1):
            e = sign * unit(g, c, thr=0.5)
            a = dict(entry=e, stop=4.0 * g.atr14.to_numpy(), tp=8.0 * g.atr14.to_numpy(),
                     exit=np.zeros(len(g)))
            I = backtest(g, a, "12h", start=START, end=IS_END, risk=0.04, max_lev=10.0,
                         max_bars_h=30 * 24)
            if I["trades"] < 20: continue
            if best is None or I["sharpe"] > best[1]["sharpe"]: best = (sign, I, a)
        if best is None:
            print(f"{c[2:]:>16}    -      - | too few trades"); continue
        sign, I, a = best
        A = backtest(g, a, "12h", start=START, end=OOS_END, risk=0.04, max_lev=10.0, max_bars_h=30 * 24)
        O = backtest(g, a, "12h", start=IS_END, end=OOS_END, risk=0.04, max_lev=10.0, max_bars_h=30 * 24)
        r = daily(A).reindex(fr.index).fillna(0.0)
        corr = float(np.corrcoef(r, fr)[0, 1])
        print(f"{c[2:]:>16}{sign:>5}{corr:>7.2f} | {A['cagr']*100:7.1f}%{A['max_dd']*100:7.1f}%"
              f"{A['profit_factor']:6.2f}{A['trades']:5d}{A['sharpe']:6.2f} | "
              f"{I['cagr']*100:7.1f}%{I['profit_factor']:6.2f} | "
              f"{O['cagr']*100:8.1f}%{O['profit_factor']:6.2f}")
        keep[c] = (sign, corr, O["profit_factor"], I["profit_factor"])
    print("\nsurvivors (IS PF > 1.05, OOS PF > 1.05, |corr| < 0.35):")
    for c, (sign, corr, opf, ipf) in keep.items():
        if ipf > 1.05 and opf > 1.05 and abs(corr) < 0.35:
            print(f"  {c[2:]:>16} sign {sign:+d}  corr {corr:+.2f}  IS PF {ipf:.2f}  OOS PF {opf:.2f}")
