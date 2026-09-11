"""
S20 - Continuous Positioning Signal (CPS)   [BTCUSDT perp only]

Every discrete strategy so far pays a full round-turn per bet, which caps how
often it can afford to act and therefore caps breadth. A continuous book instead
holds a TARGET exposure proportional to signal strength, re-evaluated every
decision bar, and trades only the CHANGE. If the signal persists, turnover is a
fraction of the notional even though the position is re-decided every bar - so
breadth rises without the cost rising proportionally.

    w_t = clip(composite_t / scale, -1, +1) x (target_vol / realised_vol) x gross

Costs are charged on |w_t - w_{t-1}| only; real funding is charged on the held
exposure. No stops: risk is controlled by the volatility target and the cap.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, IS_START, IS_END, OOS_END
from engine.weights import simulate
from engine.data import load
import strategies.s07_smart as s07

def weights(f, comp, scale=1.0, target_vol=0.5, vol_n=120, gross=1.0, cap=3.0,
            bar_h=4.0, deadband=0.0, trend_gate=False):
    c = f.close.to_numpy()
    lr = pd.Series(np.log(c)).diff()
    rv = lr.rolling(vol_n).std(ddof=0).to_numpy()*np.sqrt(365.25*24/bar_h)
    s = np.clip(np.nan_to_num(comp)/scale, -1.0, 1.0)
    if deadband > 0:
        s = np.where(np.abs(s) < deadband, 0.0, s)
    if trend_gate:
        up = c > f.ema_s.to_numpy()
        s = np.where((s > 0) & ~up, 0.0, np.where((s < 0) & up, 0.0, s))
    lev = np.divide(target_vol, rv, out=np.zeros_like(rv), where=np.isfinite(rv) & (rv > 0))
    return np.clip(np.nan_to_num(s*lev*gross), -cap, cap)

def slice_(fut, f, s, e):
    m = ((f.dt >= s) & (f.dt < e)).to_numpy()
    return f[m].reset_index(drop=True), m

if __name__ == "__main__":
    fut, f4 = panel("4h")
    f = f4[f4.dt >= "2021-01-03"].reset_index(drop=True)
    comp = s07.composite(f)
    print("S20 Continuous Positioning Signal — BTCUSDT perp, 4h rebalance")
    print(f"{'variant':<44}{'CAGR':>9}{'DD':>8}{'PF':>6}{'Shp':>6}{'Clm':>7}{'gross':>7}{'turn/yr':>9}"
          f"   {'OOS CAGR':>9}{'OOS DD':>8}")
    for scale in (0.8, 1.4):
        for tv in (0.35, 0.6, 0.9):
            for gross in (1.0, 2.0, 3.5):
                for db in (0.0, 0.25):
                    w = weights(f, comp, scale=scale, target_vol=tv, gross=gross,
                                deadband=db, cap=5.0)
                    out = {}
                    for lab, s, e in (("IS", "2021-01-03", IS_END), ("OOS", IS_END, OOS_END),
                                      ("ALL", "2021-01-03", OOS_END)):
                        sub, m = slice_(fut, f, s, e)
                        out[lab] = simulate(sub, w[m], max_w=5.0)
                    a, o = out["ALL"], out["OOS"]
                    if a["turnover_yr"] < 0.5: continue
                    print(f"sc{scale} tv{tv} gross{gross} db{db}{'':<12}"
                          f"{a['cagr']*100:8.1f}%{a['max_dd']*100:7.1f}%{a['profit_factor']:6.2f}"
                          f"{a['sharpe']:6.2f}{a['calmar']:7.2f}{a['avg_gross']:7.2f}{a['turnover_yr']:9.1f}"
                          f"   {o['cagr']*100:8.1f}%{o['max_dd']*100:7.1f}%")
