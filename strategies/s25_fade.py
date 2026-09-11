"""
S25 - Session Range FADE (SRF)   [BTCUSDT perp only]

S14 (volatility-squeeze breakout) and S24 (session-range breakout) both failed
hard - profit factors of 0.83-0.98 with win rates of 27-41%. Two independent
breakout structures losing that consistently is itself information: BTC intraday
range breaks are predominantly false. This tests the direct corollary - take the
OPPOSITE side of the break and treat the range edge as resistance rather than as
a trigger.

Note the asymmetry that makes this a real test rather than a bookkeeping trick:
costs subtract from both directions, so inverting a strategy with post-cost
PF 0.83 does NOT hand you PF 1.20. The fade has to be genuinely better than
random to survive.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, IS_START, IS_END, OOS_END
import strategies.s24_session as s24

if __name__ == "__main__":
    print("S25 Session Range Fade — BTCUSDT perp, 1h bars / 15m execution")
    print(f"{'variant':<42}{'CAGR':>9}{'DD':>8}{'PF':>6}{'N':>6}{'WR':>6}{'Shp':>6}{'Clm':>7}"
          f"   {'OOS CAGR':>9}{'OOS PF':>7}")
    for name, (ref, tr) in s24.SESSIONS.items():
        for kb in (0.0, 0.25, 0.5):
            for st, rr in ((1.5, 1.5), (2.0, 1.0), (1.0, 2.0)):
                for hold in (8, 24):
                    d, a = s24.build(ref, tr, k_break=kb, atr_stop=st, rr=rr, use_atr_stop=True)
                    a = dict(a); a["entry"] = -a["entry"]          # fade the break
                    r = {}
                    for lab, s, e in (("IS", IS_START, IS_END), ("OOS", IS_END, OOS_END),
                                      ("ALL", IS_START, OOS_END)):
                        r[lab] = backtest(d, a, "1h", start=s, end=e, risk=0.015,
                                          max_lev=10.0, max_bars_h=hold)
                    m, o = r["ALL"], r["OOS"]
                    if m["trades"] < 150: continue
                    print(f"{name} kb{kb} {st}x{rr} h{hold}{'':<7}"
                          f"{m['cagr']*100:8.1f}%{m['max_dd']*100:7.1f}%{m['profit_factor']:6.2f}"
                          f"{m['trades']:6d}{m['win_rate']*100:5.1f}%{m['sharpe']:6.2f}{m['calmar']:7.2f}"
                          f"   {o['cagr']*100:8.1f}%{o['profit_factor']:7.2f}")
