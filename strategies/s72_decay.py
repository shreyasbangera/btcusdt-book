"""
S72 - Is the edge decaying?

The yearly profile of every recent version of this book declines hard: at 10%
risk the Calmar-selected book returns +229% in 2023, +133% in 2024, +44% in
2025 and +44% in 2026.  Two readings, and they have opposite consequences:

  BENIGN   2023 was an exceptionally trending year and the later ones were not.
           The strategy is doing the same thing; the market gave less.
  FATAL    the signals are being arbitraged away, and the recent number is the
           honest forecast while the early one is history.

They can be told apart.  If it is the market, the strategy's edge per unit of
OPPORTUNITY should be flat while opportunity shrinks - the book's Sharpe holds
up while its return falls with market volatility.  If the edge is decaying, the
Sharpe falls too, and so does the raw predictive power of the signals.

Three measurements on rolling 12-month windows across the whole sample:
  1. the book's own rolling CAGR, Sharpe and profit factor
  2. BTC's own realised volatility and trendiness over the same windows
  3. each signal's raw rank-IC against forward returns, which owes nothing to
     the trading rules at all
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from research.harness import backtest, OOS_END
import strategies.s45_single as S
import strategies.s46_net as S46

def main():
    g = S.grid(S.FULL_START)
    v = S.composite(g, S46.LONG); a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(v), stop=3.0 * a, tp=6.0 * a,
               exit=(np.abs(np.nan_to_num(v)) <= 0.0).astype(float))
    m = backtest(g, arr, "12h", start=S.FULL_START, end=OOS_END, risk=0.08,
                 max_lev=10.0, max_bars_h=21 * 24)
    eq = pd.Series(m["equity"], index=pd.to_datetime(m["dt"])).resample("1D").last().dropna()
    r = eq.pct_change().fillna(0.0)
    c = g.close.to_numpy(float); dt = pd.to_datetime(g.dt)
    lr = pd.Series(np.r_[0.0, np.diff(np.log(c))], index=dt)
    fwd = np.full(len(c), np.nan); fwd[:-2] = c[2:] / c[:-2] - 1.0

    print(f"{'window ending':>14} | {'book CAGR':>10}{'Sharpe':>8}{'PF':>6} | "
          f"{'BTC vol':>8}{'BTC ret':>9}{'|trend|':>8} | {'mean signal IC':>15}")
    ends = pd.date_range(r.index[0] + pd.DateOffset(months=12), r.index[-1], freq="6MS", tz="UTC")
    for e in ends:
        s0 = e - pd.DateOffset(months=12)
        w = r[(r.index >= s0) & (r.index < e)]
        if len(w) < 200: continue
        eqw = np.cumprod(1 + w.to_numpy())
        cagr = eqw[-1] ** (365.25 / len(w)) - 1
        shp = w.mean() / w.std() * np.sqrt(365.25) if w.std() > 0 else 0
        dp = np.diff(np.r_[1.0, eqw])
        pf = dp[dp > 0].sum() / max(-dp[dp < 0].sum(), 1e-9)
        lw = lr[(lr.index >= s0) & (lr.index < e)]
        vol = lw.std() * np.sqrt(730) * 100
        btc = (np.exp(lw.sum()) - 1) * 100
        trend = abs(lw.sum()) / max(lw.abs().sum(), 1e-9)      # efficiency ratio
        mask = ((dt >= s0) & (dt < e)).to_numpy()
        ics = []
        for n in S46.LONG:
            x = g[f"s_{n}"].to_numpy(float)
            ok = mask & np.isfinite(x) & np.isfinite(fwd)
            if ok.sum() > 100:
                ic = spearmanr(x[ok], fwd[ok])[0]
                ics.append(abs(ic) if n != "fundz" else abs(ic))
        print(f"{str(e.date()):>14} | {cagr*100:9.1f}%{shp:8.2f}{pf:6.2f} | "
              f"{vol:7.0f}%{btc:8.0f}%{trend:8.3f} | {np.mean(ics):15.4f}")

if __name__ == "__main__":
    main()
