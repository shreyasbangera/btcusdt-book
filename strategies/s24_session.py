"""
S24 - Session Range Breakout (SRB)   [BTCUSDT perp only]

Crypto trades 24/7, but participation is not uniform: the Asian, European and US
hours have distinct volume and volatility profiles, and the range established in
a quiet session frequently frames the move in the next active one. This is the
classic opening-range-breakout structure adapted to a 24h market, and it is a
different KIND of signal from everything else here - it keys off intraday
structure rather than positioning, flow or trend.

Reference session -> trade session (all UTC):
    Asia   00:00-08:00  ->  London  08:00-16:00
    London 08:00-16:00  ->  US      13:00-21:00
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from engine.data import load
from engine.indicators import atr
from research.harness import backtest, IS_START, IS_END, OOS_END
from research.runner import line

SESSIONS = {
    "asia->london": ((0, 8), (8, 16)),
    "london->us":   ((8, 16), (13, 21)),
    "us->asia":     ((13, 21), (0, 8)),
}

def build(ref, trade, k_break=0.0, atr_stop=1.5, rr=2.0, use_atr_stop=True):
    d = load("fut_1h").copy()
    d["day"] = d.dt.dt.floor("D")
    h = d.dt.dt.hour.to_numpy()
    r0, r1 = ref; t0, t1 = trade
    in_ref = (h >= r0) & (h < r1)
    # reference range as known at the moment the reference session closes
    g = d[in_ref].groupby("day").agg(rh=("high", "max"), rl=("low", "min")).reset_index()
    d = d.merge(g, on="day", how="left")
    # the range is only usable from hour r1 onward on the same day
    usable = h >= r1
    d.loc[~usable, ["rh", "rl"]] = np.nan
    if t1 <= t0:                                  # session wraps past midnight
        in_tr = (h >= t0) | (h < t1)
    else:
        in_tr = (h >= t0) & (h < t1)
    a = atr(d.high.to_numpy(), d.low.to_numpy(), d.close.to_numpy(), 14)
    rh = d.rh.to_numpy(); rl = d.rl.to_numpy(); c = d.close.to_numpy()
    width = rh - rl
    up = in_tr & (c > rh + k_break * a)
    dn = in_tr & (c < rl - k_break * a)
    e = np.where(np.nan_to_num(up), 1.0, np.where(np.nan_to_num(dn), -1.0, 0.0))
    stop = atr_stop * a if use_atr_stop else np.maximum(width, 0.3 * a)
    return d, dict(entry=np.nan_to_num(e), stop=stop, tp=stop * rr,
                   exit=np.zeros(len(d)))

if __name__ == "__main__":
    print("S24 Session Range Breakout — BTCUSDT perp, 1h bars / 15m execution")
    print(f"{'variant':<40}{'CAGR':>9}{'DD':>8}{'PF':>6}{'N':>6}{'WR':>6}{'Shp':>6}{'Clm':>7}"
          f"   {'OOS CAGR':>9}{'OOS PF':>7}")
    for name, (ref, tr) in SESSIONS.items():
        for kb in (0.0, 0.25):
            for st, rr in ((1.5, 2.0), (2.5, 1.5)):
                for ua in (True, False):
                    d, a = build(ref, tr, k_break=kb, atr_stop=st, rr=rr, use_atr_stop=ua)
                    r = {}
                    for lab, s, e in (("IS", IS_START, IS_END), ("OOS", IS_END, OOS_END),
                                      ("ALL", IS_START, OOS_END)):
                        r[lab] = backtest(d, a, "1h", start=s, end=e, risk=0.015,
                                          max_lev=10.0, max_bars_h=24)
                    m, o = r["ALL"], r["OOS"]
                    if m["trades"] < 100: continue
                    print(f"{name} kb{kb} {st}x{rr} {'atr' if ua else 'rng'}{'':<6}"
                          f"{m['cagr']*100:8.1f}%{m['max_dd']*100:7.1f}%{m['profit_factor']:6.2f}"
                          f"{m['trades']:6d}{m['win_rate']*100:5.1f}%{m['sharpe']:6.2f}{m['calmar']:7.2f}"
                          f"   {o['cagr']*100:8.1f}%{o['profit_factor']:7.2f}")
