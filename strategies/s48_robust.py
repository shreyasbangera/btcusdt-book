"""
S48 - Signal transforms: is the z-score the right normalisation?

Every signal in the book is a rolling z-score: (x - mean) / sd. That is the
default, not a decision, and it has two known weaknesses on financial data.
The mean and standard deviation are both dominated by the fat tails they are
supposed to be normalising, so one violent week rescales the signal for the
whole window after it; and the mapping from raw value to z assumes a shape the
data does not have.

Three alternatives, applied identically to all five signals, changing nothing
else about the strategy:

  ROBUST   (x - rolling median) / (1.4826 x rolling MAD). Same idea, but
           neither statistic is moved by a handful of extremes.
  RANK     rolling percentile rank, mapped to +/-1. Discards magnitude
           entirely and keeps only the ordering - which the conviction test
           said was where the information lives.
  TANH     z-score squashed through tanh(z/2). Keeps the ordering, keeps some
           magnitude, and bounds the tail contribution without a hard cap.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

def robust_z(x, w):
    s = pd.Series(np.asarray(x, float))
    med = s.rolling(w).median()
    mad = (s - med).abs().rolling(w).median()
    return ((s - med) / (1.4826 * mad + 1e-12)).to_numpy()

def rank_z(x, w):
    s = pd.Series(np.asarray(x, float))
    r = s.rolling(w).rank(pct=True)
    return ((r - 0.5) * 2.0).to_numpy() * 2.0        # roughly z-scaled to +/-2

RAW = {"flow": ("ofi6_res", 480), "cmpx": ("f_cmpx_raw", 120), "btcdom": ("btc_dom_raw", 120),
       "fundz": ("fund_raw", 120), "posn": ("posn", 120)}

def build(mode):
    """Rebuild every signal on the same panel under one normalisation."""
    import strategies.s38_orth as s38
    g = S.grid(S.FULL_START)
    xf = s38.xpanel("12h")
    g = g.merge(xf[["dt", "fund", "btc_dom", "cm_px"]], on="dt", how="left")
    raws = {
        "flow": (g.ofi6_res.to_numpy(float), 480),
        "cmpx": (pd.Series(np.log(g.cm_px / g.close)).diff(6).to_numpy(), 120),
        "btcdom": (g.btc_dom.to_numpy(float), 120),
        "fundz": (-g.fund.to_numpy(float), 120),
        "posn": (g.posn.to_numpy(float), 120),
    }
    from research.runner import zs
    for k, (x, w) in raws.items():
        if mode == "z":        v = zs(x, w)
        elif mode == "robust": v = robust_z(x, w)
        elif mode == "rank":   v = rank_z(x, w)
        elif mode == "tanh":   v = 2.0 * np.tanh(zs(x, w) / 2.0)
        g[f"s_{k}"] = v
    return g

if __name__ == "__main__":
    names = ["flow", "cmpx", "btcdom", "fundz", "posn"]
    print(f"{'normalisation':>16}{'risk':>6} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'Shp':>6}{'Clm':>6}"
          f" | {'IS':>7}{'OOS':>8}{'OOSPF':>6} | {'medDD':>7}{'P>20%':>7}")
    for mode in ("z", "robust", "rank", "tanh"):
        g = build(mode)
        for risk in (0.08,):
            net = S.composite(g, names)
            a = S.book(g, net, stp=3.0, rr=2.0)
            kw = dict(risk=risk, max_lev=10.0, max_bars_h=21 * 24)
            A = backtest(g, a, "12h", start=S.FULL_START, end=OOS_END, **kw)
            I = backtest(g, a, "12h", start=S.FULL_START, end=IS_END, **kw)
            O = backtest(g, a, "12h", start=IS_END, end=OOS_END, **kw)
            r = pd.Series(A["equity"], index=pd.to_datetime(A["dt"])).resample("1D").last(
                ).dropna().pct_change().fillna(0).to_numpy()
            b = bootstrap_dd(r, n=2000)
            print(f"{mode:>16}{risk*100:5.0f}% | {A['cagr']*100:7.1f}%{A['max_dd']*100:7.1f}%"
                  f"{A['profit_factor']:6.2f}{A['trades']:6d}{A['sharpe']:6.2f}{A['calmar']:6.2f} | "
                  f"{I['cagr']*100:6.1f}%{O['cagr']*100:7.1f}%{O['profit_factor']:6.2f} | "
                  f"{b['dd_median']*100:6.1f}%{b['p_dd_worse_than_20']*100:6.0f}%")
